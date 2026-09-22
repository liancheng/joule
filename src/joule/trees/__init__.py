import dataclasses as D
from collections.abc import Callable, Iterable
from enum import Enum, StrEnum
from typing import Any, ClassVar, TypeVar, override

import tree_sitter as ts
import tree_sitter_jsonnet

from joule.maybe import head_or_none, maybe
from joule.trees.pretty import Pretty


@D.dataclass(frozen=True, order=True)
class Point:
    line: int
    column: int

    def __repr__(self) -> str:
        return f"{self.line}:{self.column}"


@D.dataclass(frozen=True)
class Span:
    start: Point
    end: Point

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


class MalformedError(Exception):
    pass


def text_of(node: ts.Node) -> str:
    if node.text is None:
        raise MalformedError(f'Node "{node.type}" has no text.')
    else:
        return node.text.decode()


def expect_node_type(node: ts.Node, *node_types: str) -> ts.Node:
    if node.type not in node_types:
        expected = " or ".join(f'"{t}"' for t in node_types)
        raise MalformedError(f'Expected {expected}, but got "{node.type}".')
    else:
        return node


def field_of(node: ts.Node, name: str) -> ts.Node:
    if (child := node.child_by_field_name(name)) is None:
        raise MalformedError(f'Node "{node.type}" has no "{name}" field.')
    else:
        return child


def enum_of[E: StrEnum](enum: type[E], node: ts.Node) -> E:
    text = text_of(node)
    try:
        return enum(text)
    except ValueError:
        raise MalformedError(f"{text!r} is not a valid {enum.__qualname__}.") from None


TreeType = TypeVar("TreeType", bound="Tree")

FromCST = Callable[[ts.Node], "Tree"]


def skip_comments(nodes: Iterable[ts.Node]) -> Iterable[ts.Node]:
    return (node for node in nodes if node.type != "comment")


@D.dataclass
class Tree:
    span: Span

    registry: ClassVar[dict[str, FromCST]] = {}

    @staticmethod
    def register(fn: FromCST, *node_types: str):
        for node_type in node_types:
            if node_type in Tree.registry:
                raise RuntimeError(f'"{node_type}" is already registered.')
            else:
                Tree.registry[node_type] = fn

    @staticmethod
    def from_source(source: str) -> Tree:
        ts_parser = ts.Parser(ts.Language(tree_sitter_jsonnet.language()))
        root = ts_parser.parse(source.encode()).root_node
        return Tree.from_cst(root)

    @staticmethod
    def from_cst(node: ts.Node) -> Tree:
        try:
            fn = Tree.registry.get(node.type, Unknown.from_cst)
            return fn(node)
        except MalformedError:
            return Malformed.from_cst(node)

    def __post_init__(self):
        pass

    @property
    def pretty(self) -> str:
        return str(PrettyTree(self))

    def to(self, expect_type: type[TreeType]) -> TreeType:
        if not isinstance(self, expect_type):
            raise TypeError(
                f"Expected {expect_type.__qualname__}, but got {type(self).__qualname__}"
            )
        else:
            return self

    @property
    def children(self) -> Iterable[Tree]:
        return []


@D.dataclass
class Expr(Tree):
    @staticmethod
    def from_cst(node: ts.Node) -> Expr:
        e = Tree.from_cst(node)
        if not isinstance(e, Expr):
            raise MalformedError(
                f'Expected an expression, but "{node.type}" built a '
                f"{type(e).__qualname__}."
            )
        else:
            return e


@D.dataclass
class Unknown(Expr):
    @staticmethod
    def from_cst(node: ts.Node) -> Unknown:
        return Unknown(span_of(node))


@D.dataclass
class Malformed(Expr):
    node_type: str

    @staticmethod
    def from_cst(node: ts.Node) -> Malformed:
        return Malformed(span_of(node), node.type)


@D.dataclass
class Paren(Expr):
    expr: Expr

    @property
    @override
    def children(self) -> Iterable[Tree]:
        yield self.expr

    @staticmethod
    def from_cst(node: ts.Node) -> Expr:
        expect_node_type(node, "parenthesized")
        expr, *_ = skip_comments(node.named_children)
        return Paren(span_of(node), Expr.from_cst(expr))

    Tree.register(from_cst, "parenthesized")


@D.dataclass
class Document(Tree):
    body: Expr

    @property
    @override
    def children(self) -> Iterable[Tree]:
        yield self.body

    @staticmethod
    def from_cst(node: ts.Node) -> Tree:
        expect_node_type(node, "document")
        body, *_ = skip_comments(node.children)
        return Document(span_of(node), Expr.from_cst(body))

    Tree.register(from_cst, "document")


@D.dataclass
class Null(Expr):
    @staticmethod
    def from_cst(node: ts.Node) -> Null:
        expect_node_type(node, "null")
        return Null(span_of(node))

    Tree.register(from_cst, "null")


@D.dataclass
class Dollar(Expr):
    @staticmethod
    def from_cst(node: ts.Node) -> Dollar:
        expect_node_type(node, "dollar")
        return Dollar(span_of(node))

    Tree.register(from_cst, "dollar")


@D.dataclass
class Super(Expr):
    @staticmethod
    def from_cst(node: ts.Node) -> Super:
        expect_node_type(node, "super")
        return Super(span_of(node))

    Tree.register(from_cst, "super")


@D.dataclass
class Self(Expr):
    @staticmethod
    def from_cst(node: ts.Node) -> Self:
        expect_node_type(node, "self")
        return Self(span_of(node))

    Tree.register(from_cst, "self")


@D.dataclass
class Bool(Expr):
    value: bool

    @staticmethod
    def from_cst(node: ts.Node) -> Bool:
        expect_node_type(node, "boolean")
        return Bool(span_of(node), value=text_of(node) == "true")

    Tree.register(from_cst, "boolean")


@D.dataclass
class Num(Expr):
    value: float

    @staticmethod
    def from_cst(node: ts.Node) -> Num:
        expect_node_type(node, "number")

        span = span_of(node)
        text = text_of(node)

        try:
            match text[:2].lower():
                case "0b" | "0o" | "0x":
                    return Num(span, value=float(int(text, base=0)))
                case _:
                    return Num(span, value=float(text))
        except ValueError:
            raise MalformedError(f"{text!r} is not a valid number.") from None

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
        expect_node_type(node, "quoted_string", "text_block")
        return (
            Str.from_quoted_string(node)
            if node.type == "quoted_string"
            else Str.from_text_block(node)
        )

    @staticmethod
    def from_quoted_string(node: ts.Node) -> Str:
        expect_node_type(node, "quoted_string")

        start, *body, end = node.children
        expect_node_type(start, "string_start")
        expect_node_type(end, "string_end")

        return (
            Str(span_of(node), value="".join(Str.unescape_verbatim_string(body)))
            if text_of(start).startswith("@")
            else Str(span_of(node), value="".join(Str.unescape_string(body)))
        )

    def unescape_verbatim_string(body: list[ts.Node]) -> Iterable[str]:
        for child in body:
            text = text_of(child)
            yield text[0] if child.type == "escape_sequence" else text

    def unescape_string(body: list[ts.Node]) -> Iterable[str]:
        code_units: list[int] = []

        def flush_code_units() -> Iterable[str]:
            if len(code_units) > 0:
                encoded = b"".join(u.to_bytes(2, "big") for u in code_units)
                code_units.clear()

                try:
                    yield encoded.decode("utf-16-be", "strict")
                except UnicodeDecodeError:
                    # A `\uXXXX` escape can name an unpaired surrogate, which is
                    # what half of a typed-out surrogate pair looks like.
                    raise MalformedError("Unpaired surrogate escape.") from None

        for child in body:
            text = text_of(child)

            if child.type != "escape_sequence":
                yield from flush_code_units()
                yield text
            elif text.startswith("\\u"):
                code_units.append(int(text[-4:], 16))
            elif (unescaped := Str.simple_escapes.get(text[1:2])) is not None:
                yield from flush_code_units()
                yield unescaped
            else:
                raise MalformedError(f"Unknown escape sequence: {text!r}.")

        yield from flush_code_units()

    @staticmethod
    def from_text_block(node: ts.Node) -> Str:
        expect_node_type(node, "text_block")

        start, *body, end = node.children
        expect_node_type(start, "text_block_start")
        expect_node_type(end, "text_block_end")

        content = "".join(
            text_of(child)
            for child in body
            if child.type in ("text_block_line_content", "text_block_blank_line")
        )

        if text_of(start).endswith("-"):
            content = content[:-1]

        return Str(span_of(node), value=content)

    Tree.register(from_cst, "quoted_string", "text_block")


class Id:
    @D.dataclass
    class Var(Tree):
        name: str

        @staticmethod
        def from_cst(node: ts.Node) -> Id.Var:
            expect_node_type(node, "var_id")
            return Id.Var(span_of(node), name=text_of(node))

        def __post_init__(self):
            super().__post_init__()
            self.binding: VarBinding | None = None
            self.references: list[Id.VarRef] = []

        Tree.register(from_cst, "var_id")

    @D.dataclass
    class VarRef(Expr):
        name: str

        @staticmethod
        def from_cst(node: ts.Node) -> Id.VarRef:
            expect_node_type(node, "var_ref_id")
            return Id.VarRef(span_of(node), name=text_of(node))

        def __post_init__(self):
            super().__post_init__()
            self.var: Id.Var | None = None

        Tree.register(from_cst, "var_ref_id")

    @D.dataclass
    class Field(Tree):
        name: str

        @staticmethod
        def from_cst(node: ts.Node) -> Id.Field:
            expect_node_type(node, "field_id")
            return Id.Field(span_of(node), name=text_of(node))

        @staticmethod
        def from_string(string: Str) -> Id.Field:
            return Id.Field(string.span, name=string.value)

        def __post_init__(self):
            super().__post_init__()
            self.binding: FieldBinding | None = None

        Tree.register(from_cst, "field_id")

    @D.dataclass
    class FieldRef(Tree):
        name: str

        @staticmethod
        def from_cst(node: ts.Node) -> Id.FieldRef:
            expect_node_type(node, "field_ref_id")
            return Id.FieldRef(span_of(node), name=text_of(node))

        Tree.register(from_cst, "field_ref_id")

    @D.dataclass
    class ParamRef(Tree):
        name: str

        @staticmethod
        def from_cst(node: ts.Node) -> Id.ParamRef:
            expect_node_type(node, "param_ref_id")
            return Id.ParamRef(span_of(node), name=text_of(node))

        Tree.register(from_cst, "param_ref_id")


@D.dataclass
class Array(Expr):
    values: list[Expr]

    @property
    @override
    def children(self) -> Iterable[Tree]:
        yield from self.values

    @staticmethod
    def from_cst(node: ts.Node) -> Array:
        expect_node_type(node, "array")
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

    @property
    @override
    def children(self) -> Iterable[Tree]:
        yield self.operand

    @staticmethod
    def from_cst(node: ts.Node) -> Unary:
        expect_node_type(node, "unary")
        op, operand, *_ = skip_comments(node.named_children)

        return Unary(
            span_of(node),
            op=enum_of(UnaryOp, op),
            operand=Expr.from_cst(operand),
        )

    Tree.register(from_cst, "unary")


@D.dataclass
class Binary(Expr):
    op: BinaryOp
    lhs: Expr
    rhs: Expr

    @property
    @override
    def children(self) -> Iterable[Tree]:
        yield self.lhs
        yield self.rhs

    @staticmethod
    def from_cst(node: ts.Node) -> Binary:
        expect_node_type(node, "binary", "object_apply")

        match node.type:
            case "binary":
                lhs, op, rhs, *_ = skip_comments(node.named_children)
                operator = enum_of(BinaryOp, op)

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

    @property
    @override
    def children(self) -> Iterable[Tree]:
        yield self.importee

    @staticmethod
    def from_cst(node: ts.Node) -> Import:
        expect_node_type(node, "import")
        kind, path, *_ = skip_comments(node.named_children)
        return Import(
            span_of(node),
            kind=enum_of(ImportKind, kind),
            importee=Importee.from_string(Str.from_cst(path)),
        )

    Tree.register(from_cst, "import")


@D.dataclass
class Assert(Tree):
    condition: Expr
    message: Expr | None = None

    @property
    @override
    def children(self) -> Iterable[Tree]:
        yield self.condition
        yield from maybe(self.message)

    @staticmethod
    def from_cst(node: ts.Node) -> Assert:
        expect_node_type(node, "assert")
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

    @property
    @override
    def children(self) -> Iterable[Tree]:
        yield self.assertion
        yield self.body

    @staticmethod
    def from_cst(node: ts.Node) -> AssertedExpr:
        expect_node_type(node, "asserted_expr")
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

    @property
    @override
    def children(self) -> Iterable[Tree]:
        yield self.name
        yield from maybe(self.default)

    @staticmethod
    def from_cst(node: ts.Node) -> Param:
        expect_node_type(node, "param")

        var, *_ = skip_comments(node.children)
        maybe_default = maybe(node.child_by_field_name("default"))

        return Param(
            span_of(node),
            name=Id.Var.from_cst(var),
            default=head_or_none(Expr.from_cst(e) for e in maybe_default),
        )

    Tree.register(from_cst, "param")


class Params:
    @staticmethod
    def from_cst(node: ts.Node) -> list[Param]:
        expect_node_type(node, "params")
        return [Param.from_cst(n) for n in skip_comments(node.named_children)]


@D.dataclass
class Fn(Expr):
    params: list[Param]
    body: Expr

    @property
    @override
    def children(self) -> Iterable[Tree]:
        yield from self.params
        yield self.body

    @staticmethod
    def from_cst(node: ts.Node) -> Fn:
        expect_node_type(node, "function")
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

    @property
    @override
    def children(self) -> Iterable[Tree]:
        yield self.name
        yield self.value

    @staticmethod
    def from_cst(node: ts.Node) -> Bind:
        expect_node_type(node, "binding")
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

    @property
    @override
    def children(self) -> Iterable[Tree]:
        yield from self.binds
        yield self.body

    @staticmethod
    def from_cst(node: ts.Node) -> Local:
        expect_node_type(node, "local")
        binds, body, *_ = skip_comments(node.named_children)
        return Local(
            span_of(node),
            binds=[Bind.from_cst(n) for n in skip_comments(binds.named_children)],
            body=Expr.from_cst(body),
        )

    Tree.register(from_cst, "local")


@D.dataclass
class If(Expr):
    condition: Expr
    consequence: Expr
    alternative: Expr | None = None

    @property
    @override
    def children(self) -> Iterable[Tree]:
        yield self.condition
        yield self.consequence
        yield from maybe(self.alternative)

    @staticmethod
    def from_cst(node: ts.Node) -> If:
        expect_node_type(node, "conditional")
        condition, consequence, *rest = skip_comments(node.named_children)

        match rest:
            case [ts.Node() as m, *_]:
                alternative = Expr.from_cst(m)
            case _:
                alternative = None

        return If(
            span_of(node),
            condition=Expr.from_cst(condition),
            consequence=Expr.from_cst(consequence),
            alternative=alternative,
        )

    Tree.register(from_cst, "conditional")


@D.dataclass
class Arg(Tree):
    value: Expr
    name: Id.ParamRef | None = None

    @property
    @override
    def children(self) -> Iterable[Tree]:
        yield self.value
        yield from maybe(self.name)

    @staticmethod
    def from_cst(node: ts.Node) -> Arg:
        expect_node_type(node, "argument")

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

    @property
    @override
    def children(self) -> Iterable[Tree]:
        yield self.fn
        yield from self.args

    @staticmethod
    def from_cst(node: ts.Node) -> Call:
        expect_node_type(node, "call")
        fn, args, *_ = skip_comments(node.named_children)
        return Call(
            span_of(node),
            fn=Expr.from_cst(fn),
            args=[Arg.from_cst(n) for n in skip_comments(args.named_children)],
        )

    Tree.register(from_cst, "call")


@D.dataclass
class FieldAccess(Expr):
    target: Expr
    field: Id.FieldRef

    @property
    @override
    def children(self) -> Iterable[Tree]:
        yield self.target
        yield self.field

    @staticmethod
    def from_cst(node: ts.Node) -> FieldAccess:
        expect_node_type(node, "field_access")
        obj, field, *_ = skip_comments(node.named_children)
        return FieldAccess(
            span_of(node),
            target=Expr.from_cst(obj),
            field=Id.FieldRef.from_cst(field),
        )

    Tree.register(from_cst, "field_access")


@D.dataclass
class Slice(Tree):
    start: Expr | None = None
    end: Expr | None = None
    step: Expr | None = None

    @property
    @override
    def children(self) -> Iterable[Tree]:
        yield from maybe(self.start)
        yield from maybe(self.end)
        yield from maybe(self.step)

    @staticmethod
    def from_cst(node: ts.Node) -> Slice:
        expect_node_type(node, "slice")

        def part(name: str) -> Expr | None:
            return head_or_none(
                Expr.from_cst(n) for n in maybe(node.child_by_field_name(name))
            )

        return Slice(
            span_of(node),
            start=part("start"),
            end=part("end"),
            step=part("step"),
        )

    Tree.register(from_cst, "slice")


@D.dataclass
class Index(Expr):
    target: Expr
    index: Expr | Slice

    @property
    @override
    def children(self) -> Iterable[Tree]:
        yield self.target
        yield self.index

    @staticmethod
    def from_cst(node: ts.Node) -> Index:
        expect_node_type(node, "index")
        obj, index_or_slice, *_ = skip_comments(node.named_children)
        return Index(
            span_of(node),
            target=Expr.from_cst(obj),
            index=(
                Slice.from_cst(index_or_slice)
                if index_or_slice.type == "slice"
                else Expr.from_cst(index_or_slice)
            ),
        )

    Tree.register(from_cst, "index")


@D.dataclass
class ForSpec(Tree):
    id: Id.Var
    source: Expr

    @property
    @override
    def children(self) -> Iterable[Tree]:
        yield self.id
        yield self.source

    @staticmethod
    def from_cst(node: ts.Node) -> ForSpec:
        expect_node_type(node, "for_spec")
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

    @property
    @override
    def children(self) -> Iterable[Tree]:
        yield self.condition

    @staticmethod
    def from_cst(node: ts.Node) -> IfSpec:
        expect_node_type(node, "if_spec")
        condition, *_ = skip_comments(node.named_children)
        return IfSpec(span_of(node), condition=Expr.from_cst(condition))

    Tree.register(from_cst, "if_spec")


CompSpec = ForSpec | IfSpec


@D.dataclass
class ArrayComp(Expr):
    expr: Expr
    for_spec: ForSpec
    extra_specs: list[CompSpec]

    @property
    @override
    def children(self) -> Iterable[Tree]:
        yield self.expr
        yield self.for_spec
        yield from self.extra_specs

    @staticmethod
    def from_cst(node: ts.Node) -> ArrayComp:
        expect_node_type(node, "array_comp")
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
        expect_node_type(node, "static_key", "computed_key")
        return (
            StaticKey.from_cst(node)
            if node.type == "static_key"
            else ComputedKey.from_cst(node)
        )


@D.dataclass
class StaticKey(FieldKey):
    id: Id.Field

    @property
    @override
    def children(self) -> Iterable[Tree]:
        yield self.id

    @staticmethod
    def from_cst(node: ts.Node) -> StaticKey:
        expect_node_type(node, "static_key")

        span = span_of(node)
        key, *_ = skip_comments(node.named_children)

        return (
            StaticKey(span, Id.Field.from_cst(key))
            if key.type == "field_id"
            else StaticKey(span, Id.Field.from_string(Str.from_cst(key)))
        )

    Tree.register(from_cst, "static_key")


@D.dataclass
class ComputedKey(FieldKey):
    expr: Expr

    @property
    @override
    def children(self) -> Iterable[Tree]:
        yield self.expr

    @staticmethod
    def from_cst(node: ts.Node) -> ComputedKey:
        expect_node_type(node, "computed_key")
        expr, *_ = skip_comments(node.named_children)
        return ComputedKey(span_of(node), expr=Expr.from_cst(expr))

    Tree.register(from_cst, "computed_key")


@D.dataclass
class Field(Tree):
    key: FieldKey
    value: Expr
    inherited: bool = False
    visibility: Visibility = Visibility.Default

    @property
    @override
    def children(self) -> Iterable[Tree]:
        yield self.key
        yield self.value

    @staticmethod
    def from_cst(node: ts.Node) -> Field:
        expect_node_type(node, "field")

        key = FieldKey.from_cst(field_of(node, "key"))
        inherited = node.child_by_field_name("inherited") is not None
        visibility = enum_of(Visibility, field_of(node, "visibility"))

        if (params := node.child_by_field_name("parameters")) is not None:
            body = field_of(node, "body")
            value = Fn(
                span_of(params).merge(span_of(body)),
                params=Params.from_cst(params),
                body=Expr.from_cst(body),
            )
        else:
            value = Expr.from_cst(field_of(node, "value"))

        return Field(
            span_of(node),
            key=key,
            inherited=inherited,
            visibility=visibility,
            value=value,
        )

    Tree.register(from_cst, "field")


@D.dataclass
class Object(Expr):
    binds: list[Bind] = D.field(default_factory=list)
    asserts: list[Assert] = D.field(default_factory=list)
    fields: list[Field] = D.field(default_factory=list)

    member_parsers: ClassVar[dict[str, FromCST]] = {
        "assert": Assert.from_cst,
        "field": Field.from_cst,
        "object_local": Bind.from_cst,
    }

    @property
    @override
    def children(self) -> Iterable[Tree]:
        yield from self.binds
        yield from self.asserts
        yield from self.fields

    @staticmethod
    def from_cst(node: ts.Node) -> Object:
        expect_node_type(node, "object")

        binds: list[Bind] = []
        asserts: list[Assert] = []
        fields: list[Field] = []

        for member in skip_comments(node.named_children):
            match member.type:
                case "object_local":
                    bind, *_ = skip_comments(member.named_children)
                    binds.append(Bind.from_cst(bind))
                case "assert":
                    asserts.append(Assert.from_cst(member))
                case _:
                    fields.append(Field.from_cst(member))

        return Object(span_of(node), binds=binds, asserts=asserts, fields=fields)

    Tree.register(from_cst, "object")


@D.dataclass
class ObjComp(Expr):
    field: Field
    for_spec: ForSpec
    binds: list[Bind] = D.field(default_factory=list)
    extra_specs: list[CompSpec] = D.field(default_factory=list)

    @property
    @override
    def children(self) -> Iterable[Tree]:
        yield from self.binds
        yield self.field
        yield self.for_spec
        yield from self.extra_specs

    @staticmethod
    def from_cst(node: ts.Node) -> ObjComp:
        expect_node_type(node, "object_comp")

        binds: list[Bind] = []
        extra_specs: list[CompSpec] = []

        for local in node.children_by_field_name("object_local"):
            bind, *_ = skip_comments(local.named_children)
            binds.append(Bind.from_cst(bind))

        for spec in node.children_by_field_name("extra_specs"):
            extra_specs.append(
                IfSpec.from_cst(spec)
                if spec.type == "if_spec"
                else ForSpec.from_cst(spec)
            )

        key = field_of(node, "key")
        params = node.child_by_field_name("parameters")
        value_or_body = field_of(node, "value_or_body")

        value = (
            Expr.from_cst(value_or_body)
            if params is None
            else Fn(
                span_of(params).merge(span_of(value_or_body)),
                params=Params.from_cst(params),
                body=Expr.from_cst(value_or_body),
            )
        )

        return ObjComp(
            span_of(node),
            field=Field(
                span_of(key).merge(span_of(value_or_body)),
                key=ComputedKey.from_cst(key),
                value=value,
                inherited=node.child_by_field_name("inherited") is not None,
                visibility=Visibility.Default,
            ),
            for_spec=ForSpec.from_cst(field_of(node, "for_spec")),
            binds=binds,
            extra_specs=extra_specs,
        )

    Tree.register(from_cst, "object_comp")


@D.dataclass
class Error(Expr):
    expr: Expr

    @property
    @override
    def children(self) -> Iterable[Tree]:
        yield self.expr

    @staticmethod
    def from_cst(node: ts.Node) -> Error:
        expect_node_type(node, "error")
        expr, *_ = skip_comments(node.named_children)
        return Error(span_of(node), Expr.from_cst(expr))

    Tree.register(from_cst, "error")


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


@D.dataclass
class VarBinding:
    """A class representing a variable bound to a target in a variable scope.

    The type of the target is `Tree` instead of `Expr`, because a variable can be bound
    to a for-spec in a list-/object-comprehension, and a for-spec is not an expression.
    """

    scope: VarScope
    id: Id.Var
    target: Tree


@D.dataclass
class VarScope:
    owner: Tree
    bindings: list[VarBinding] = D.field(default_factory=list)
    parent: VarScope | None = None
    children: list[VarScope] = D.field(default_factory=list)

    def bind(self, var: Id.Var, to: Tree):
        var.binding = VarBinding(self, var, to)
        self.bindings.insert(0, var.binding)

    def get(self, name: str) -> VarBinding | None:
        return next(
            iter(b for b in self.bindings if b.id.name == name),
            None if self.parent is None else self.parent.get(name),
        )

    def nest(self, owner: Tree) -> VarScope:
        child = VarScope(owner, [], parent=self)
        self.children.append(child)
        return child

    @staticmethod
    def empty(owner: Tree) -> VarScope:
        return VarScope(owner)


@D.dataclass
class FieldBinding:
    """A class representing a static field key bound to a field value."""

    scope: FieldScope
    id: Id.Field
    target: Field


@D.dataclass
class FieldScope:
    owner: Object
    bindings: list[FieldBinding] = D.field(default_factory=list)
    parent: FieldScope | None = None
    children: list[FieldScope] = D.field(default_factory=list)

    def bind(self, key: StaticKey, to: Field):
        key.id.binding = FieldBinding(self, key.id, to)
        self.bindings.insert(0, key.id.binding)

    def get(self, name: str) -> FieldBinding | None:
        return next(
            iter(b for b in self.bindings if b.id.name == name),
            None if self.parent is None else self.parent.get(name),
        )

    def nest(self, owner: Object) -> FieldScope:
        child = FieldScope(owner, [], parent=self)
        self.children.append(child)
        return child

    @staticmethod
    def empty(owner: Object) -> FieldScope:
        return FieldScope(owner)
