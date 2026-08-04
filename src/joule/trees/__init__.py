import dataclasses as D
from collections.abc import Callable, Iterable
from enum import Enum, StrEnum
from typing import Any, ClassVar, TypeVar

import lsprotocol.types as L
import tree_sitter as ts
import tree_sitter_jsonnet

from joule.maybe import just, maybe
from joule.trees.pretty import Pretty


@D.dataclass(frozen=True, order=True)
class Point:
    line: int
    character: int

    @staticmethod
    def from_lsp(pos: L.Position):
        return Point(pos.line, pos.character)

    @property
    def lsp(self):
        return L.Position(self.line, self.character)

    def __repr__(self) -> str:
        return f"{self.line}:{self.character}"


@D.dataclass(frozen=True)
class Span:
    start: Point
    end: Point

    @staticmethod
    def from_lsp(range: L.Range):
        return Span(Point.from_lsp(range.start), Point.from_lsp(range.end))

    @property
    def lsp(self) -> L.Range:
        return L.Range(self.start.lsp, self.end.lsp)

    def __eq__(self, other) -> bool:
        return (
            isinstance(other, Span)
            and self.start == other.start
            and self.end == other.end
        )

    def __repr__(self) -> str:
        return f"{self.start!r}-{self.end!r}"

    def contains(self, other: Point | Span) -> bool:
        if isinstance(other, Point):
            other = Span(other, other)
        return self.start <= other.start and other.end <= self.end

    def merge(self, other: Span) -> Span:
        return Span(
            min(self.start, other.start),
            max(self.end, other.end),
        )


def point_of(point: ts.Point) -> Point:
    return Point(point.row, point.column)


def span_of(node: ts.Node) -> Span:
    return Span(point_of(node.start_point), point_of(node.end_point))


def text_of(node: ts.Node) -> str:
    return just(node.text).decode()


TreeType = TypeVar("TreeType", bound="Tree")

FromCST = Callable[[ts.Node], "Tree"]


def skip_comments(nodes: Iterable[ts.Node]) -> Iterable[ts.Node]:
    return (node for node in nodes if node.type != "comment")


@D.dataclass
class Tree:
    span: Span

    ts_parser: ClassVar[ts.Parser] = ts.Parser(
        ts.Language(tree_sitter_jsonnet.language())
    )

    registry: ClassVar[dict[str, FromCST]] = {}

    @staticmethod
    def register(fn: FromCST, *node_types: str):
        for node_type in node_types:
            assert node_type not in Tree.registry, f'"{node_type}" already registered.'
            Tree.registry[node_type] = fn

    @staticmethod
    def from_source(source: str) -> Tree:
        root = Tree.ts_parser.parse(source.encode()).root_node
        return Tree.from_cst(root)

    @staticmethod
    def from_cst(node: ts.Node) -> Tree:
        try:
            fn = Tree.registry.get(node.type, Unknown.from_cst)
            return fn(node)
        except AssertionError:
            return Error.from_cst(node)

    @property
    def pretty(self) -> str:
        return str(PrettyTree(self))

    def to(self, expect_type: type[TreeType]) -> TreeType:
        if not isinstance(self, expect_type):
            raise TypeError(
                f"Expected {expect_type.__qualname__}, but got {type(self).__qualname__}"
            )

        return self

    @property
    def children(self) -> Iterable[Tree]:
        return []


@D.dataclass
class Unknown(Tree):
    @staticmethod
    def from_cst(node: ts.Node) -> Tree:
        return Unknown(span_of(node))


@D.dataclass
class Error(Tree):
    node_type: str

    @staticmethod
    def from_cst(node: ts.Node) -> Tree:
        return Error(span_of(node), node.type)


@D.dataclass
class Expr(Tree):
    @staticmethod
    def from_cst(node: ts.Node) -> Expr:
        e = Tree.from_cst(node)
        assert isinstance(e, Expr)
        return e


@D.dataclass
class Document(Tree):
    body: Expr

    @staticmethod
    def from_cst(node: ts.Node) -> Tree:
        assert node.type == "document"
        body, *_ = skip_comments(node.children)
        return Document(span_of(node), Expr.from_cst(body))

    Tree.register(from_cst, "document")


@D.dataclass
class Null(Expr):
    @staticmethod
    def from_cst(node: ts.Node) -> Null:
        assert node.type == "null"
        return Null(span_of(node))

    Tree.register(from_cst, "null")


@D.dataclass
class Dollar(Expr):
    @staticmethod
    def from_cst(node: ts.Node) -> Dollar:
        assert node.type == "dollar"
        return Dollar(span_of(node))

    Tree.register(from_cst, "dollar")


@D.dataclass
class Super(Expr):
    @staticmethod
    def from_cst(node: ts.Node) -> Super:
        assert node.type == "super"
        return Super(span_of(node))

    Tree.register(from_cst, "super")


@D.dataclass
class Self(Expr):
    @staticmethod
    def from_cst(node: ts.Node) -> Self:
        assert node.type == "self"
        return Self(span_of(node))

    Tree.register(from_cst, "self")


@D.dataclass
class Bool(Expr):
    value: bool

    @staticmethod
    def from_cst(node: ts.Node) -> Bool:
        assert node.type == "boolean"
        return Bool(span_of(node), value=just(node.text) == b"true")

    Tree.register(from_cst, "boolean")


@D.dataclass
class Num(Expr):
    value: float

    @staticmethod
    def from_cst(node: ts.Node) -> Num:
        assert node.type == "number"

        span = span_of(node)
        text = just(node.text).decode()

        match text[:2].lower():
            case "0b" | "0o" | "0x":
                return Num(span, value=float(int(text, base=0)))
            case _:
                return Num(span, value=float(text))

    Tree.register(from_cst, "number")


@D.dataclass
class Str(Expr):
    value: str

    # Escape sequences standing for a single character, keyed by the character
    # following the backslash.
    simple_escapes: ClassVar[dict[str, str]] = {
        '"': '"',
        "'": "'",
        "\\": "\\",
        "/": "/",
        "b": "\b",
        "f": "\f",
        "n": "\n",
        "r": "\r",
        "t": "\t",
    }

    @staticmethod
    def from_cst(node: ts.Node) -> Str:
        assert node.type in ("quoted_string", "text_block")
        return (
            Str.from_quoted_string(node)
            if node.type == "quoted_string"
            else Str.from_text_block(node)
        )

    @staticmethod
    def from_quoted_string(node: ts.Node) -> Str:
        assert node.type == "quoted_string"

        start, *body, end = node.children
        assert start.type == "string_start"
        assert end.type == "string_end"

        return (
            Str(span_of(node), value="".join(Str.unescape_verbatim_string(body)))
            if text_of(start).startswith("@")
            else Str(span_of(node), value="".join(Str.unescape_string(body)))
        )

    def unescape_verbatim_string(body: list[ts.Node]) -> Iterable[str]:
        for child in body:
            text = just(child.text).decode()
            yield text[0] if child.type == "escape_sequence" else text

    def unescape_string(body: list[ts.Node]) -> Iterable[str]:
        code_units: list[int] = []

        def flush_code_units() -> Iterable[str]:
            if len(code_units) > 0:
                encoded = b"".join(u.to_bytes(2, "big") for u in code_units)
                code_units.clear()
                yield encoded.decode("utf-16-be", "strict")

        for child in body:
            match just(child.text).decode():
                case text if child.type != "escape_sequence":
                    yield from flush_code_units()
                    yield text
                case text if text.startswith("\\u"):
                    code_units.append(int(text[-4:], 16))
                case _:
                    yield from flush_code_units()
                    yield Str.simple_escapes[text[1]]

        yield from flush_code_units()

    @staticmethod
    def from_text_block(node: ts.Node) -> Str:
        assert node.type == "text_block"

        start, *body, end = node.children
        assert start.type == "text_block_start"
        assert end.type == "text_block_end"

        content = "".join(
            text_of(child)
            for child in body
            if child.type in ("text_block_line_content", "text_block_blank_line")
        )

        if just(start.text).endswith(b"-"):
            content = content[:-1]

        return Str(span_of(node), value=content)

    Tree.register(from_cst, "quoted_string", "text_block")


class Id:
    @D.dataclass
    class Var(Expr):
        name: str

        @staticmethod
        def from_cst(node: ts.Node) -> Id.Var:
            assert node.type == "var_id"
            return Id.Var(span_of(node), name=just(node.text).decode())

        Tree.register(from_cst, "var_id")

    @D.dataclass
    class VarRef(Expr):
        name: str

        @staticmethod
        def from_cst(node: ts.Node) -> Id.VarRef:
            assert node.type == "var_ref_id"
            return Id.VarRef(span_of(node), name=just(node.text).decode())

        Tree.register(from_cst, "var_ref_id")

    @D.dataclass
    class Field(Expr):
        name: str

        @staticmethod
        def from_cst(node: ts.Node) -> Id.Field:
            assert node.type == "field_id"
            return Id.Field(span_of(node), name=just(node.text).decode())

        @staticmethod
        def from_string(string: Str) -> Id.Field:
            return Id.Field(string.span, name=string.value)

        Tree.register(from_cst, "field_id")

    @D.dataclass
    class FieldRef(Expr):
        name: str

        @staticmethod
        def from_cst(node: ts.Node) -> Id.FieldRef:
            assert node.type == "field_ref_id"
            return Id.FieldRef(span_of(node), name=just(node.text).decode())

        Tree.register(from_cst, "field_ref_id")

    @D.dataclass
    class ParamRef(Expr):
        name: str

        @staticmethod
        def from_cst(node: ts.Node) -> Id.ParamRef:
            assert node.type == "param_ref_id"
            return Id.ParamRef(span_of(node), name=just(node.text).decode())

        Tree.register(from_cst, "param_ref_id")


@D.dataclass
class Array(Expr):
    values: list[Expr]

    @staticmethod
    def from_cst(node: ts.Node) -> Array:
        assert node.type == "array"
        values = [Expr.from_cst(child) for child in skip_comments(node.named_children)]
        return Array(span_of(node), values)

    Tree.register(from_cst, "array")


class UnaryOp(StrEnum):
    Plus = "+"
    Negate = "-"
    Not = "!"
    BitNot = "~"

    def __call__(self, span: Span, operand: Expr) -> Unary:
        return Unary(span, self, operand)


class BinaryOp(StrEnum):
    Multiply = "*"
    Divide = "/"
    Modulus = "%"

    Plus = "+"
    Minus = "-"

    ShiftLeft = "<<"
    ShiftRight = ">>"

    LT = "<"
    LE = "<="
    GT = ">"
    GE = ">="
    In = "in"

    Eq = "=="
    NotEq = "!="

    BitAnd = "&"
    BitXor = "^"
    BitOr = "|"
    And = "&&"
    Or = "||"

    def __call__(self, lhs: Expr, rhs) -> Binary:
        return Binary(lhs.span.merge(rhs.span), self, lhs, rhs)


@D.dataclass
class Unary(Expr):
    op: UnaryOp
    operand: Expr

    @staticmethod
    def from_cst(node: ts.Node) -> Unary:
        assert node.type == "unary"
        op, operand, *_ = skip_comments(node.named_children)

        return Unary(
            span_of(node),
            op=UnaryOp(just(op.text).decode()),
            operand=Expr.from_cst(operand),
        )

    Tree.register(from_cst, "unary")


@D.dataclass
class Binary(Expr):
    op: BinaryOp
    lhs: Expr
    rhs: Expr

    @staticmethod
    def from_cst(node: ts.Node) -> Binary:
        assert node.type in ("binary", "object_apply")

        match node.type:
            case "binary":
                lhs, op, rhs, *_ = skip_comments(node.named_children)
                operator = BinaryOp(just(op.text).decode())

            case "object_apply":
                lhs, rhs, *_ = skip_comments(node.named_children)
                operator = BinaryOp.Plus

        return Binary(span_of(node), operator, Expr.from_cst(lhs), Expr.from_cst(rhs))

    Tree.register(from_cst, "binary", "object_apply")


class ImportKind(StrEnum):
    Default = "import"
    Str = "importstr"
    Bin = "importbin"


@D.dataclass
class Importee(Str):
    @staticmethod
    def from_string(string: Str) -> Importee:
        return Importee(string.span, string.value)


@D.dataclass
class Import(Expr):
    kind: ImportKind
    importee: Importee

    @staticmethod
    def from_cst(node: ts.Node) -> Import:
        assert node.type == "import"
        kind, path, *_ = skip_comments(node.named_children)
        return Import(
            span_of(node),
            kind=ImportKind(just(kind.text).decode()),
            importee=Importee.from_string(Str.from_cst(path)),
        )

    Tree.register(from_cst, "import")


@D.dataclass
class Assert(Tree):
    condition: Expr
    message: Expr | None = None

    @staticmethod
    def from_cst(node: ts.Node) -> Assert:
        assert node.type == "assert"
        condition, *rest = skip_comments(node.named_children)

        match rest:
            case [ts.Node() as m, *_]:
                message = Expr.from_cst(m)
            case _:
                message = None

        return Assert(
            span_of(node),
            condition=Expr.from_cst(condition),
            message=message,
        )

    Tree.register(from_cst, "assert")


@D.dataclass
class AssertedExpr(Expr):
    assertion: Assert
    body: Expr

    @staticmethod
    def from_cst(node: ts.Node) -> AssertedExpr:
        assert node.type == "asserted_expr"
        assertion, body, *_ = skip_comments(node.named_children)
        return AssertedExpr(
            span_of(node),
            assertion=Assert.from_cst(assertion),
            body=Expr.from_cst(body),
        )

    Tree.register(from_cst, "asserted_expr")


@D.dataclass
class Param(Tree):
    name: Id.Var
    default: Expr | None = None

    @staticmethod
    def from_cst(node: ts.Node) -> Param:
        assert node.type == "param"

        var, *_ = skip_comments(node.children)
        maybe_default = maybe(node.child_by_field_name("default"))

        return Param(
            span_of(node),
            name=Id.Var.from_cst(var),
            default=next((Expr.from_cst(e) for e in maybe_default), None),
        )

    Tree.register(from_cst, "param")


@D.dataclass
class Fn(Expr):
    params: list[Param]
    body: Expr

    @staticmethod
    def from_cst(node: ts.Node) -> Fn:
        assert node.type == "function"
        params, body, *_ = skip_comments(node.named_children)

        return Fn(
            span_of(node),
            params=[Param.from_cst(n) for n in skip_comments(params.named_children)],
            body=Expr.from_cst(body),
        )

    Tree.register(from_cst, "function")


@D.dataclass
class Bind(Tree):
    name: Id.Var
    value: Expr

    @staticmethod
    def from_cst(node: ts.Node) -> Bind:
        assert node.type == "binding"
        return (
            Bind.bind_var(node)
            if node.child_by_field_name("function") is None
            else Bind.bind_fn(node)
        )

    @staticmethod
    def bind_fn(node: ts.Node) -> Bind:
        fn_name, params, body, *_ = skip_comments(node.named_children)
        return Bind(
            span_of(node),
            name=Id.Var.from_cst(fn_name),
            value=Fn(
                span_of(params).merge(span_of(body)),
                params=[
                    Param.from_cst(n) for n in skip_comments(params.named_children)
                ],
                body=Expr.from_cst(body),
            ),
        )

    @staticmethod
    def bind_var(node: ts.Node) -> Bind:
        var, value, *_ = skip_comments(node.named_children)
        return Bind(
            span_of(node),
            name=Id.Var.from_cst(var),
            value=Expr.from_cst(value),
        )

    Tree.register(from_cst, "binding")


@D.dataclass
class Local(Expr):
    binds: list[Bind]
    body: Expr

    @staticmethod
    def from_cst(node: ts.Node) -> Local:
        assert node.type == "local"
        binds, body, *_ = skip_comments(node.named_children)
        return Local(
            span_of(node),
            binds=[Bind.from_cst(n) for n in skip_comments(binds.named_children)],
            body=Expr.from_cst(body),
        )

    Tree.register(from_cst, "local")


@D.dataclass
class Arg(Expr):
    value: Expr
    name: Id.ParamRef | None = None

    @staticmethod
    def from_cst(node: ts.Node) -> Arg:
        assert node.type == "argument"

        match node.child_by_field_name("name"):
            case None:
                value, *_ = skip_comments(node.named_children)
                return Arg(
                    span_of(node),
                    value=Expr.from_cst(value),
                )

            case _:
                name, value, *_ = skip_comments(node.named_children)
                return Arg(
                    span_of(node),
                    value=Expr.from_cst(value),
                    name=Id.ParamRef.from_cst(name),
                )

    Tree.register(from_cst, "argument")


@D.dataclass
class Call(Expr):
    fn: Expr
    args: list[Arg]

    @staticmethod
    def from_cst(node: ts.Node) -> Call:
        assert node.type == "call"
        fn, args, *_ = skip_comments(node.named_children)
        return Call(
            span_of(node),
            fn=Expr.from_cst(fn),
            args=[Arg.from_cst(n) for n in args.named_children],
        )

    Tree.register(from_cst, "call")


@D.dataclass
class ForSpec(Tree):
    id: Id.Var
    source: Expr

    @staticmethod
    def from_cst(node: ts.Node) -> ForSpec:
        assert node.type == "for_spec"
        id, source, *_ = skip_comments(node.named_children)
        return ForSpec(
            span_of(node),
            id=Id.Var.from_cst(id),
            source=Expr.from_cst(source),
        )

    Tree.register(from_cst, "for_spec")


@D.dataclass
class IfSpec(Tree):
    condition: Expr

    @staticmethod
    def from_cst(node: ts.Node) -> IfSpec:
        assert node.type == "if_spec"
        condition, *_ = skip_comments(node.named_children)
        return IfSpec(span_of(node), condition=Expr.from_cst(condition))

    Tree.register(from_cst, "if_spec")


CompSpec = ForSpec | IfSpec


@D.dataclass
class ArrayComp(Expr):
    expr: Expr
    for_spec: ForSpec
    extra_specs: list[CompSpec]

    @staticmethod
    def from_cst(node: ts.Node) -> ArrayComp:
        assert node.type == "array_comp"
        expr, for_spec, *extra_specs = skip_comments(node.named_children)
        return ArrayComp(
            span_of(node),
            expr=Expr.from_cst(expr),
            for_spec=ForSpec.from_cst(for_spec),
            extra_specs=[
                ForSpec.from_cst(spec)
                if spec.type == "for_spec"
                else IfSpec.from_cst(spec)
                for spec in extra_specs
            ],
        )

    Tree.register(from_cst, "array_comp")


class Visibility(StrEnum):
    Default = ":"
    Hidden = "::"
    Forced = ":::"


@D.dataclass
class FieldKey(Tree):
    @staticmethod
    def from_cst(node: ts.Node) -> FieldKey:
        assert node.type == "field_key"
        span = span_of(node)

        match node.child_by_field_name("expression"):
            case ts.Node() as expr:
                return ComputedKey(span, expr=Expr.from_cst(expr))

            case None:
                key, *_ = skip_comments(node.named_children)
                return (
                    FixedKey(span, Id.Field.from_cst(key))
                    if key.type == "field_id"
                    else FixedKey(span, Id.Field.from_string(Str.from_cst(key)))
                )

    Tree.register(from_cst, "field_key")


@D.dataclass
class FixedKey(FieldKey):
    id: Id.Field


@D.dataclass
class ComputedKey(FieldKey):
    expr: Expr


@D.dataclass
class Field(Tree):
    key: FieldKey
    value: Expr
    inherited: bool = False
    visibility: Visibility = Visibility.Default

    @staticmethod
    def from_cst(node: ts.Node) -> Field:
        assert node.type == "field"

        key = FieldKey.from_cst(just(node.child_by_field_name("key")))
        inherited = node.child_by_field_name("inherit") is not None
        visibility = next(
            Visibility(text.decode())
            for n in maybe(node.child_by_field_name("visibility"))
            for text in maybe(n.text)
        )

        if (params := node.child_by_field_name("parameters")) is not None:
            body = just(node.child_by_field_name("body"))
            value = Fn(
                span_of(params).merge(span_of(body)),
                params=[
                    Param.from_cst(n) for n in skip_comments(params.named_children)
                ],
                body=Expr.from_cst(body),
            )
        else:
            value = Expr.from_cst(just(node.child_by_field_name("value")))

        return Field(
            span_of(node),
            key=key,
            inherited=inherited,
            visibility=visibility,
            value=value,
        )


@D.dataclass
class PrettyTree(Pretty):
    """A class for pretty-printing a Jsonnet AST."""

    node: Any

    label: str | None = None

    def node_text(self) -> str:
        match self.node:
            case Tree() as tree:
                # For all other nodes, only prints the range.
                repr = f"{tree.__class__.__qualname__} [{tree.span}]"
            case Enum():
                repr = self.node.name
            case list():
                # For lists, print a placeholder as all the elements are printed
                # separately as child nodes.
                repr = "list"
            case str() if len(self.node) > 256:
                repr = f"{self.node[: 256 - 5] + '[...]'!r}"
            case str():
                repr = f"{self.node!r}"
            case _:
                # Falls back to `__str__` for everything else.
                repr = str(self.node)

        # Prepends the label, if any.
        return repr if self.label is None else f"{self.label}={repr}"

    def children(self) -> list[Pretty]:
        match self.node:
            case Tree():
                return [
                    PrettyTree(node=field_value, label=field.name)
                    for field, field_value in self.non_empty_fields(self.node)
                    if field.name != "span"
                ]
            case list() as array if (size := len(array)) > 0:
                return [PrettyTree(node=array[i], label=f"[{i}]") for i in range(size)]
            case _:
                return []

    def __repr__(self):
        return super().__repr__()
