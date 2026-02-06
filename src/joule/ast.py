import dataclasses as D
from enum import StrEnum
from itertools import chain, dropwhile
from textwrap import dedent
from typing import (
    Annotated,
    Any,
    Callable,
    ClassVar,
    Iterable,
    Iterator,
    Type,
    TypeVar,
    cast,
)

import lsprotocol.types as L
import tree_sitter as T

from joule.pretty import PrettyTree
from joule.util import head_or_none, maybe

URI = Annotated[str, "URI"]


def strip_comments(nodes: list[T.Node]) -> list[T.Node]:
    return [node for node in nodes if not node.type == "comment"]


ParseCST = Callable[[str, T.Node], "AST"]

ASTType = TypeVar("ASTType", bound="AST")


@D.dataclass
class AST:
    location: L.Location

    registry: ClassVar[dict[str, ParseCST]] = {}

    @staticmethod
    def register(fn: ParseCST, *node_types: str):
        for node_type in node_types:
            assert node_type not in AST.registry, f'"{node_type}" already registered.'
            AST.registry[node_type] = fn

    @staticmethod
    def skip_paren(uri: URI, node: T.Node):
        return AST.from_cst(uri, strip_comments(node.named_children)[0])

    @staticmethod
    def from_cst(uri: URI, node: T.Node) -> "AST":
        try:
            cst_parser = AST.registry.get(node.type, Unknown.from_cst)
            return cst_parser(uri, node)
        except Exception:
            return ErrorAST.from_cst(uri, node)

    @classmethod
    def has_var_scope(cls) -> bool:
        return False

    @classmethod
    def has_field_scope(cls) -> bool:
        return False

    def __post_init__(self):
        self.parent: AST | None = None
        self.var_scope: Scope | None = None

        for child in self.children:
            child.parent = self

    def to(self, expect_type: Type[ASTType]) -> ASTType:
        if not isinstance(self, expect_type):
            raise TypeError(
                f"Expected {expect_type.__qualname__}, but got {type(self).__name__}"
            )

        return self

    def set_var_scope(self, scope: Scope):
        self.var_scope = scope

    @property
    def pretty_tree(self) -> str:
        return str(PrettyAST(self))

    @property
    def children(self) -> Iterable["AST"]:
        return []

    def node_at(self, target: L.Position | L.Range) -> "AST | None":
        """Returns the narrowest AST node covering the target location."""
        if isinstance(target, L.Position):
            target = L.Range(target, target)

        candidate = head_or_none(
            node
            for child in self.children
            if range_contains(child.location.range, target)
            for node in maybe(child.node_at(target))
        )

        match candidate:
            case None if range_contains(self.location.range, target):
                return self
            case None:
                return None
            case node:
                return node


def skip_parenthesis(uri: URI, node: T.Node) -> "Expr":
    return Expr.from_cst(uri, strip_comments(node.named_children)[0])


AST.register(skip_parenthesis, "parenthesis")


ESCAPE_TABLE: dict[int, str] = str.maketrans(
    {"\n": r"\n", "\t": r"\t", "\r": r"\r", '"': r"\""}
)


def escape(s: str, size: int = 50) -> str:
    escaped = s[0:size].translate(ESCAPE_TABLE)
    postfix = "" if len(s) <= size else f"[{len(s) - size} characters]"
    return f'"{escaped}{postfix}"'


@D.dataclass
class PrettyAST(PrettyTree):
    """A class for pretty-printing a Jsonnet AST."""

    node: Any
    label: str | None = None

    def node_text(self) -> str:
        match self.node:
            case Document() as doc:
                # For the top-level `Document` node, prints the full location with URI.
                repr = f"{doc.__class__.__qualname__} [{doc.location}]"
            case AST() as ast:
                # For all other nodes, only prints the range.
                repr = f"{ast.__class__.__qualname__} [{ast.location.range}]"
            case _, *_:
                # For lists, print a placeholder as all the elements are printed
                # separately as child nodes.
                repr = "[...]"
            case str():
                # Escapes (and truncates) strings, which can potentially be multi-line.
                repr = escape(self.node)
            case _:
                # Falls back to `__str__` for everything else.
                repr = str(self.node)

        # Prepends the label, if any.
        return repr if self.label is None else f"{self.label}={repr}"

    def children(self) -> list["PrettyTree"]:
        match self.node:
            case AST() as ast:
                return [
                    PrettyAST(getattr(ast, f.name), f.name)
                    for f in D.fields(ast)
                    if f.name != "location"
                ]
            case list() as array if (size := len(array)) > 0:
                return [PrettyAST(array[i], f"[{i}]") for i in range(size)]
            case _:
                return []

    def __repr__(self):
        return super().__repr__()


@D.dataclass
class PrettyCST(PrettyTree):
    """A class for pretty-printing a tree-sitter CST."""

    node: T.Node
    label: str | None = None

    def node_text(self) -> str:
        if not self.node.is_named and self.node.text:
            repr = f"{escape(self.node.text.decode())} [{range_of(self.node)}]"
        else:
            repr = f"{self.node.type} [{range_of(self.node)}]"

        return repr if self.label is None else f"{self.label}={repr}"

    def children(self) -> list["PrettyTree"]:
        return [
            PrettyCST(child, self.node.field_name_for_child(i))
            for i, child in enumerate(self.node.children)
        ]

    def __repr__(self):
        return super().__repr__()


@D.dataclass
class Expr(AST):
    @staticmethod
    def from_cst(uri: URI, node: T.Node) -> "Expr":
        match AST.from_cst(uri, node):
            case Expr() as e:
                return e
            case _:
                return ErrorExpr(location_of(uri, node), node.type)

    @property
    def tails(self) -> list["Expr"]:
        return [self]

    def arg(self, name: "Id.ParamRef | None" = None) -> "Arg":
        location = merge_locations(name, self) if name else self.location
        return Arg(location, self, name)

    def bin_op(self, op: "Operator", rhs: "Expr") -> "Binary":
        return Binary(merge_locations(self, rhs), op, self, rhs)

    def __add__(self, rhs: "Expr") -> "Binary":
        return self.bin_op(Operator.Plus, rhs)

    def __sub__(self, rhs: "Expr") -> "Binary":
        return self.bin_op(Operator.Minus, rhs)

    def __mul__(self, rhs: "Expr") -> "Binary":
        return self.bin_op(Operator.Multiply, rhs)

    def __truediv__(self, rhs: "Expr") -> "Binary":
        return self.bin_op(Operator.Divide, rhs)

    def __lt__(self, rhs: "Expr") -> "Binary":
        return self.bin_op(Operator.LT, rhs)

    def __le__(self, rhs: "Expr") -> "Binary":
        return self.bin_op(Operator.LE, rhs)

    def __gt__(self, rhs: "Expr") -> "Binary":
        return self.bin_op(Operator.GT, rhs)

    def __ge__(self, rhs: "Expr") -> "Binary":
        return self.bin_op(Operator.GE, rhs)

    def eq(self, rhs: object) -> "Binary":
        assert isinstance(rhs, Expr)
        return self.bin_op(Operator.Eq, rhs)

    def not_eq(self, rhs: "Expr") -> "Binary":
        return self.bin_op(Operator.NotEq, rhs)


@D.dataclass
class Self(Expr):
    def __post_init__(self):
        self.scope: Scope | None = None

    @staticmethod
    def from_cst(uri: URI, node: T.Node) -> "Self":
        assert node.type == "self"
        return Self(location_of(uri, node))

    AST.register(from_cst, "self")


@D.dataclass
class Super(Expr):
    def __post_init__(self):
        self.scope: Scope | None = None

    @staticmethod
    def from_cst(uri: URI, node: T.Node) -> "Super":
        assert node.type == "super"
        return Super(location_of(uri, node))

    AST.register(from_cst, "super")


@D.dataclass
class Document(Expr):
    body: Expr

    @classmethod
    def has_var_scope(cls) -> bool:
        return True

    @property
    def children(self) -> list[AST]:
        return [self.body]

    @property
    def tails(self) -> list[Expr]:
        return self.body.tails

    @staticmethod
    def from_cst(uri: URI, node: T.Node) -> "Document":
        assert node.type == "document"
        body, *_ = strip_comments(node.named_children)
        return Document(location_of(uri, node), Expr.from_cst(uri, body))

    AST.register(from_cst, "document")


class Id:
    @D.dataclass
    class Var(Expr):
        name: str

        @staticmethod
        def from_cst(uri: URI, node: T.Node) -> "Id.Var":
            assert node.type == "id"
            assert node.text is not None
            return Id.Var(location_of(uri, node), node.text.decode())

        def bind(self, value: Expr) -> "Bind":
            return Bind(merge_locations(self, value), self, value)

        def param(self, default: Expr | None = None) -> "Param":
            location = merge_locations(self, default) if default else self.location
            return Param(location, self, default)

    @D.dataclass
    class VarRef(Expr):
        name: str

        def __post_init__(self):
            super().__post_init__()
            self.bound_in: Scope | None = None

        @staticmethod
        def from_cst(uri: URI, node: T.Node) -> "Id.VarRef":
            assert node.type == "id"
            assert node.text is not None
            return Id.VarRef(location_of(uri, node), node.text.decode())

        AST.register(from_cst, "id")

    @D.dataclass
    class Field(Expr):
        name: str

        @staticmethod
        def from_cst(uri: URI, node: T.Node) -> "Id.Field":
            assert node.type == "id"
            assert node.text is not None
            return Id.Field(location_of(uri, node), node.text.decode())

    @D.dataclass
    class FieldRef(Expr):
        name: str

        @staticmethod
        def from_cst(uri: URI, node: T.Node) -> "Id.FieldRef":
            assert node.type == "id"
            assert node.text is not None
            return Id.FieldRef(location_of(uri, node), node.text.decode())

    @D.dataclass
    class ParamRef(Expr):
        name: str

        @staticmethod
        def from_cst(uri: URI, node: T.Node) -> "Id.ParamRef":
            assert node.type == "id"
            assert node.text is not None
            return Id.ParamRef(location_of(uri, node), node.text.decode())


@D.dataclass
class Num(Expr):
    value: float

    @staticmethod
    def from_cst(uri: URI, node: T.Node) -> "Num":
        assert node.type == "number"
        assert node.text is not None
        return Num(location_of(uri, node), float(node.text.decode()))

    AST.register(from_cst, "number")


@D.dataclass
class Str(Expr):
    raw: str

    @staticmethod
    def from_cst(uri: URI, node: T.Node) -> "Str":
        assert node.type == "string"

        _, content, _ = node.named_children
        assert content.text is not None

        return Str(
            location=location_of(uri, node),
            # The raw string content before escaping or indentations are handled.
            raw=content.text.decode(),
        )

    AST.register(from_cst, "string")


@D.dataclass
class Bool(Expr):
    value: bool

    @staticmethod
    def from_cst(uri: URI, node: T.Node) -> "Bool":
        assert node.type in ["true", "false"]
        assert node.text is not None
        return Bool(location_of(uri, node), node.text.decode() == "true")

    AST.register(from_cst, "false", "true")


@D.dataclass
class Array(Expr):
    values: list[Expr]

    @property
    def children(self) -> Iterable[AST]:
        return iter(cast(AST, value) for value in self.values)

    @staticmethod
    def from_cst(uri: URI, node: T.Node) -> "Array":
        assert node.type == "array"
        return Array(
            location=location_of(uri, node),
            values=[
                Expr.from_cst(uri, child)
                for child in strip_comments(node.named_children)
            ],
        )

    AST.register(from_cst, "array")


class Operator(StrEnum):
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


@D.dataclass
class Binary(Expr):
    op: Operator
    lhs: Expr
    rhs: Expr

    @property
    def children(self) -> list[AST]:
        return [self.lhs, self.rhs]

    @staticmethod
    def from_cst(uri: URI, node: T.Node) -> "Binary":
        assert node.type in ["binary", "implicit_plus"]

        match node.type:
            case "binary":
                lhs, op, rhs, *_ = strip_comments(node.named_children)
                assert op.text is not None
                operator = Operator(op.text.decode())
            case _:
                lhs, rhs, *_ = strip_comments(node.named_children)
                operator = Operator.Plus

        return Binary(
            location=location_of(uri, node),
            op=operator,
            lhs=Expr.from_cst(uri, lhs),
            rhs=Expr.from_cst(uri, rhs),
        )

    AST.register(from_cst, "binary", "implicit_plus")


@D.dataclass
class Bind(AST):
    id: Id.Var
    value: Expr

    @property
    def children(self) -> list[AST]:
        return [self.id, self.value]

    @staticmethod
    def from_cst(uri: URI, node: T.Node) -> "Bind":
        assert node.type == "bind"

        children = strip_comments(node.named_children)

        if (fn_name := node.child_by_field_name("function")) is not None:
            maybe_params = maybe(node.child_by_field_name("params"))
            first_body, *_ = strip_comments(node.children_by_field_name("body"))

            fn = Fn(
                location=location_of(uri, node),
                params=[
                    Param.from_cst(uri, param)
                    for params in maybe_params
                    for param in strip_comments(params.named_children)
                ],
                body=Expr.from_cst(uri, first_body),
            )

            return Bind(
                location=fn.location,
                id=Id.Var.from_cst(uri, fn_name),
                value=fn,
            )
        else:
            id, value, *_ = children
            return Bind(
                location=location_of(uri, node),
                id=Id.Var.from_cst(uri, id),
                value=Expr.from_cst(uri, value),
            )

    AST.register(from_cst, "bind")


@D.dataclass
class Local(Expr):
    binds: list[Bind]
    body: Expr

    @property
    def tails(self) -> list[Expr]:
        return self.body.tails

    @property
    def children(self) -> Iterable[AST]:
        return chain(self.binds, [self.body])

    @classmethod
    def has_var_scope(cls) -> bool:
        return True

    @staticmethod
    def from_cst(uri: URI, node: T.Node) -> "Local":
        assert node.type == "local_bind"

        # Skips the first node, which is the "local" keyword.
        _, *children = strip_comments(node.named_children)

        binds, body = [], []
        for child in children:
            (binds if child.type == "bind" else body).append(child)

        return Local(
            location=location_of(uri, node),
            binds=[Bind.from_cst(uri, bind) for bind in binds],
            body=Expr.from_cst(uri, body[0]),
        )

    AST.register(from_cst, "local_bind")


@D.dataclass
class Param(AST):
    id: Id.Var
    default: Expr | None = None

    @property
    def children(self) -> Iterable[AST]:
        return chain([self.id], iter(maybe(self.default)))

    @staticmethod
    def from_cst(uri: URI, node: T.Node) -> "Param":
        assert node.type == "param"

        children = strip_comments(node.named_children)
        assert 1 <= len(children) <= 2

        id, *maybe_default = children
        return Param(
            location=location_of(uri, node),
            id=Id.Var.from_cst(uri, id),
            default=head_or_none(Expr.from_cst(uri, value) for value in maybe_default),
        )

    AST.register(from_cst, "param")


@D.dataclass
class Fn(Expr):
    params: list[Param]
    body: Expr

    @property
    def children(self) -> Iterable[AST]:
        return chain(self.params, [self.body])

    @property
    def tails(self) -> list[Expr]:
        return self.body.tails

    @classmethod
    def has_var_scope(cls) -> bool:
        return True

    @staticmethod
    def from_cst(uri: URI, node: T.Node) -> "Fn":
        assert node.type == "anonymous_function"
        first, *rest = strip_comments(node.named_children)

        match first, rest:
            case _, (body, *_) if first.type == "params":
                params = [
                    Param.from_cst(uri, param)
                    for param in strip_comments(first.named_children)
                ]
            case body, *_:
                params = []

        return Fn(
            location=location_of(uri, node),
            params=params,
            body=Expr.from_cst(uri, body),
        )

    AST.register(from_cst, "anonymous_function")


@D.dataclass
class Arg(AST):
    value: Expr
    name: Id.ParamRef | None = None

    @property
    def children(self) -> Iterable[AST]:
        return chain([self.value], maybe(self.name))

    @staticmethod
    def from_cst(uri: URI, node: T.Node) -> "Arg":
        if node.type == "named_argument":
            name, value = strip_comments(node.named_children)

            return Arg(
                location=location_of(uri, node),
                value=Expr.from_cst(uri, value),
                name=Id.ParamRef.from_cst(uri, name),
            )
        else:
            return Arg(
                location=location_of(uri, node),
                value=Expr.from_cst(uri, node),
            )

    AST.register(from_cst, "named_argument")


@D.dataclass
class Call(Expr):
    fn: Expr
    args: list[Arg]

    @property
    def children(self) -> Iterable[AST]:
        return chain([self.fn], self.args)

    @staticmethod
    def from_cst(uri: URI, node: T.Node) -> "Call":
        assert node.type == "functioncall"

        children = strip_comments(node.named_children)
        assert len(children) >= 1

        fn, *maybe_args = children

        return Call(
            location=location_of(uri, node),
            fn=Expr.from_cst(uri, fn),
            args=[
                Arg.from_cst(uri, arg)
                for args in maybe_args
                for arg in strip_comments(args.named_children)
            ],
        )

    AST.register(from_cst, "functioncall")


@D.dataclass
class ForSpec(AST):
    id: Id.Var
    source: Expr

    @property
    def children(self) -> Iterable[AST]:
        return [self.id, self.source]

    @classmethod
    def has_var_scope(cls) -> bool:
        return True

    @staticmethod
    def from_cst(uri: URI, node: T.Node) -> "ForSpec":
        assert node.type == "forspec"
        id, expr = strip_comments(node.named_children)

        return ForSpec(
            location_of(uri, node),
            Id.Var.from_cst(uri, id),
            Expr.from_cst(uri, expr),
        )

    AST.register(from_cst, "forspec")


@D.dataclass
class IfSpec(AST):
    condition: Expr

    @property
    def children(self) -> list[AST]:
        return [self.condition]

    @staticmethod
    def from_cst(uri: URI, node: T.Node) -> "IfSpec":
        assert node.type == "ifspec"
        [child] = strip_comments(node.named_children)
        return IfSpec(location_of(uri, node), condition=Expr.from_cst(uri, child))

    AST.register(from_cst, "ifspec")


CompSpec = list[ForSpec | IfSpec]


@D.dataclass
class ListComp(Expr):
    expr: Expr
    for_spec: ForSpec
    comp_spec: CompSpec

    @property
    def children(self) -> Iterable[AST]:
        return chain([self.expr, self.for_spec], self.comp_spec)

    @classmethod
    def has_var_scope(cls) -> bool:
        return True

    @staticmethod
    def from_cst(uri: URI, node: T.Node) -> "ListComp":
        assert node.type == "forloop"

        children = strip_comments(node.named_children)
        assert len(children) >= 2

        expr, for_spec, *maybe_comp_spec = children
        return ListComp(
            location=location_of(uri, node),
            expr=Expr.from_cst(uri, expr),
            for_spec=ForSpec.from_cst(uri, for_spec),
            comp_spec=[
                ForSpec.from_cst(uri, spec)
                if spec.type == "forspec"
                else IfSpec.from_cst(uri, spec)
                for comp_spec in maybe_comp_spec
                for spec in strip_comments(comp_spec.named_children)
            ],
        )

    AST.register(from_cst, "forloop")


@D.dataclass
class Import(Expr):
    type: str
    path: Str

    @property
    def children(self) -> list[AST]:
        return [self.path]

    @staticmethod
    def from_cst(uri: URI, node: T.Node) -> "Import":
        assert node.type in ["import", "importbin", "importstr"]

        [path] = strip_comments(node.named_children)
        return Import(
            location_of(uri, node),
            node.type,
            Str.from_cst(uri, path),
        )

    AST.register(from_cst, "import", "importbin", "importstr")


@D.dataclass
class Assert(AST):
    condition: Expr
    message: Expr | None = None

    @property
    def children(self) -> Iterable[AST]:
        return chain([self.condition], maybe(self.message))

    @staticmethod
    def from_cst(uri: URI, node: T.Node) -> "Assert":
        assert node.type == "assert"

        children = strip_comments(node.named_children)
        assert 1 <= len(children) <= 2

        condition, *maybe_message = children

        match maybe_message:
            case child, *_:
                message = Expr.from_cst(uri, child)
            case _:
                message = None

        return Assert(
            location_of(uri, node),
            condition=Expr.from_cst(uri, condition),
            message=message,
        )

    def guard(self, body: Expr) -> "AssertExpr":
        return AssertExpr(merge_locations(self, body), self, body)


@D.dataclass
class AssertExpr(Expr):
    assertion: Assert
    body: Expr

    @property
    def tails(self) -> list[Expr]:
        return self.body.tails

    @property
    def children(self) -> list[AST]:
        return [self.assertion, self.body]

    @staticmethod
    def from_cst(uri: URI, node: T.Node) -> Expr:
        # An `AssertExpr` is an expression consisting of an assertion followed by an
        # expression. Ideally, one expression should map to one `Expr` node and one
        # tree-sitter node. However, `AssertExpr` breaks this nice property.
        #
        # Consider the following assert expression:
        #
        #   assert true;
        #   assert true;
        #   x + 1
        #
        # If tree-sitter returns the following tree, it would be straightforward to
        # parse:
        #
        #   <assert_expr>
        #       <assert>
        #           <true>
        #       <assert_expr>
        #           <assert>
        #               <true>
        #           <binary>
        #               left: <id>
        #               operator: <additive>
        #               right: <id>
        #
        # However, `tree-sitter-jsonnet` explicitly hides the top node by prefixing the
        # rule name with an underscore (`_assert_expr` instead of `assert_expr`), which
        # forces the parser to return a forest of trees:
        #
        #   <assert>
        #       <true>
        #   <assert>
        #       <true>
        #   <binary>
        #       left: <id>
        #       operator: <additive>
        #       right: <id>
        #
        # This unnecessarily complicates the parsing logic, because an `Expr` node may
        # map to one or more tree-sitter nodes.

        def named_siblings(node: T.Node) -> Iterator[T.Node]:
            sibling = node.next_named_sibling
            while sibling is not None:
                yield sibling
                sibling = sibling.next_named_sibling

        # Finds the first non-comment sibling named node. This is the first node of the
        # body expression.
        no_comments = dropwhile(
            lambda sibling: sibling.is_extra,
            named_siblings(node),
        )

        assertion = Assert.from_cst(uri, node)
        body = Expr.from_cst(uri, next(no_comments))

        return AssertExpr(merge_locations(assertion, body), assertion, body)

    AST.register(from_cst, "assert")


class Visibility(StrEnum):
    Default = ":"
    Hidden = "::"
    Forced = ":::"


@D.dataclass
class FieldKey(AST):
    @staticmethod
    def from_cst(uri: URI, node: T.Node) -> "FieldKey":
        assert node.type == "fieldname"

        location = location_of(uri, node)
        head, *tail = strip_comments(node.children)
        assert head.text is not None

        if head.text.decode() == "[":
            e, *_ = tail
            return ComputedKey(location, Expr.from_cst(uri, e))
        elif head.type == "id":
            return FixedKey(location, Id.Field.from_cst(uri, head))
        else:
            return FixedKey(location, Str.from_cst(uri, head))

    AST.register(from_cst, "fieldname")

    def map_to(
        self,
        value: Expr,
        visibility: Visibility = Visibility.Default,
        inherited: bool = False,
    ) -> "Field":
        return Field(
            merge_locations(self.location, value.location),
            self,
            value,
            visibility,
            inherited,
        )


@D.dataclass
class FixedKey(FieldKey):
    id: Id.Field | Str

    @property
    def name(self) -> str:
        match self.id:
            case Id.Field(_, name):
                return name
            case Str(_, raw):
                return raw

    @property
    def children(self) -> list[AST]:
        return [self.id]


@D.dataclass
class ComputedKey(FieldKey):
    expr: Expr

    @property
    def children(self) -> list[AST]:
        return [self.expr]


@D.dataclass
class Field(AST):
    key: FieldKey
    value: Expr
    visibility: Visibility = Visibility.Default
    inherited: bool = False

    @property
    def children(self) -> list[AST]:
        return [self.key, self.value]

    @staticmethod
    def from_cst(uri: URI, node: T.Node) -> "Field":
        assert node.type == "field"
        children = strip_comments(node.children)

        def parse_function_field(children: list[T.Node]) -> Field:
            key, lparen, params_or_rparen, *rest = children

            match params_or_rparen:
                case n if n.type == "params":
                    _, vis, body, *_ = rest
                    params = [
                        Param.from_cst(uri, param)
                        for param in strip_comments(n.named_children)
                    ]
                case _:
                    params = []
                    vis, body, *_ = rest

            assert vis.text is not None
            return Field(
                location=location_of(uri, node),
                key=FieldKey.from_cst(uri, key),
                value=Fn(
                    L.Location(uri, merge_ranges(lparen, body)),
                    params=params,
                    body=Expr.from_cst(uri, body),
                ),
                visibility=Visibility(vis.text.decode()),
            )

        def parse_value_field(children: list[T.Node]) -> Field:
            key, plus_or_vis, *rest = children

            match plus_or_vis:
                case plus if plus.text == b"+":
                    vis, value, *_ = rest
                    assert vis.text is not None
                    inherited = True
                case vis:
                    assert vis.text is not None
                    value, *_ = rest
                    inherited = False

            return Field(
                location=location_of(uri, node),
                key=FieldKey.from_cst(uri, key),
                value=Expr.from_cst(uri, value),
                visibility=Visibility(vis.text.decode()),
                inherited=inherited,
            )

        return (
            parse_function_field(children)
            if len(node.children_by_field_name("function")) > 0
            else parse_value_field(children)
        )

    AST.register(from_cst, "field")


@D.dataclass
class Object(Expr):
    binds: list[Bind] = D.field(default_factory=list)
    assertions: list[Assert] = D.field(default_factory=list)
    fields: list[Field] = D.field(default_factory=list)

    def __post_init__(self):
        self.field_scope: Scope | None = None

    def set_field_scope(self, scope: Scope):
        self.field_scope = scope

    @property
    def children(self) -> Iterable[AST]:
        return chain(self.binds, self.assertions, self.fields)

    @classmethod
    def has_var_scope(cls) -> bool:
        return True

    @classmethod
    def has_field_scope(cls) -> bool:
        return True

    @staticmethod
    def from_cst(uri: URI, node: T.Node) -> "Object | ObjComp":
        assert node.type == "object"

        if any(child.type == "forspec" for child in node.named_children):
            return ObjComp.from_cst(uri, node)
        else:
            binds = []
            asserts = []
            fields = []

            for member in strip_comments(node.named_children):
                assert member.type == "member"
                head, *_ = strip_comments(member.named_children)
                match head.type:
                    case "objlocal":
                        _, bind, *_ = strip_comments(head.named_children)
                        binds.append(Bind.from_cst(uri, bind))
                    case "assert":
                        asserts.append(Assert.from_cst(uri, head))
                    case "field":
                        fields.append(Field.from_cst(uri, head))

            return Object(location_of(uri, node), binds, asserts, fields)

    AST.register(from_cst, "object")


@D.dataclass
class ObjComp(Expr):
    field: Field
    binds: list[Bind]
    asserts: list[Assert]
    for_spec: ForSpec
    comp_spec: CompSpec = D.field(default_factory=list)

    def __post_init__(self):
        super().__post_init__()
        assert isinstance(self.field.key, ComputedKey)

    @property
    def children(self) -> Iterable[AST]:
        return chain(
            [self.field],
            self.binds,
            self.asserts,
            [self.for_spec],
            self.comp_spec,
        )

    @classmethod
    def has_var_scope(cls) -> bool:
        return True

    @staticmethod
    def from_cst(uri: URI, node: T.Node) -> "ObjComp":
        assert node.type == "object"

        obj_locals = []
        asserts = []
        fields = []
        for_specs = []
        maybe_comp_spec = []

        for child in strip_comments(node.named_children):
            match child.type:
                case "member":
                    match strip_comments(child.named_children):
                        case [member] if member.type == "field":
                            fields.append(member)
                        case [member] if member.type == "objlocal":
                            obj_locals.append(member)
                        case [member] if member.type == "assert":
                            asserts.append(member)
                        case _:
                            pass
                case "forspec":
                    for_specs.append(child)
                case "compspec":
                    maybe_comp_spec.append(child)

        match [Field.from_cst(uri, f) for f in fields]:
            case [Field(_, ComputedKey(), _) as field]:
                pass
            case _:
                raise ValueError(
                    "An object comprehension must have exactly 1 field with a computed key."
                )

        match [ForSpec.from_cst(uri, s) for s in for_specs]:
            case [for_spec]:
                pass
            case _:
                raise ValueError(
                    "An object comprehension must have exactly 1 for-spec."
                )

        assert len(maybe_comp_spec) <= 1

        def local_bind_from_cst(node: T.Node) -> Bind:
            assert node.type == "objlocal"
            _, bind, *_ = strip_comments(node.named_children)
            return Bind.from_cst(uri, bind)

        return ObjComp(
            location=location_of(uri, node),
            field=field,
            binds=[local_bind_from_cst(local) for local in obj_locals],
            asserts=[Assert.from_cst(uri, assertion) for assertion in asserts],
            for_spec=for_spec,
            comp_spec=[
                ForSpec.from_cst(uri, spec)
                if spec.type == "forspec"
                else IfSpec.from_cst(uri, spec)
                for comp_spec in maybe_comp_spec
                for spec in strip_comments(comp_spec.named_children)
            ],
        )


@D.dataclass
class FieldAccess(Expr):
    obj: Expr
    field: Id.FieldRef

    @property
    def children(self) -> Iterable[AST]:
        return [self.obj, self.field]

    @staticmethod
    def from_cst(uri: URI, node: T.Node) -> "FieldAccess":
        assert node.type in ["fieldaccess", "fieldaccess_super"]
        expr, field = strip_comments(node.named_children)
        return FieldAccess(
            location=location_of(uri, node),
            obj=Expr.from_cst(uri, expr),
            field=Id.FieldRef.from_cst(uri, field),
        )

    AST.register(from_cst, "fieldaccess_super", "fieldaccess")


@D.dataclass
class Slice(Expr):
    array: Expr
    begin: Expr
    end: Expr | None = None
    step: Expr | None = None

    @property
    def children(self) -> Iterable[AST]:
        return chain(
            [self.array, self.begin],
            maybe(self.end),
            maybe(self.step),
        )

    @staticmethod
    def from_cst(uri: URI, node: T.Node) -> "Slice":
        assert node.type == "indexing"
        expr, begin, *rest = strip_comments(node.named_children)
        match rest:
            case [end, step]:
                end = Expr.from_cst(uri, end)
                step = Expr.from_cst(uri, step)
            case [end]:
                end = Expr.from_cst(uri, end)
                step = None
            case _:
                end = None
                step = None

        return Slice(
            location=location_of(uri, node),
            array=Expr.from_cst(uri, expr),
            begin=Expr.from_cst(uri, begin),
            end=end,
            step=step,
        )

    AST.register(from_cst, "indexing")


@D.dataclass
class If(Expr):
    condition: Expr
    consequence: Expr
    alternative: Expr | None

    @property
    def tails(self) -> list[Expr]:
        return self.consequence.tails + [
            tail
            for alternative in maybe(self.alternative)
            for tail in alternative.tails
        ]

    @property
    def children(self) -> Iterable[AST]:
        return chain([self.condition, self.consequence], maybe(self.alternative))

    @staticmethod
    def from_cst(uri: URI, node: T.Node) -> "If":
        assert node.type == "conditional"
        condition, consequence, *maybe_alternative = strip_comments(node.named_children)
        return If(
            location=location_of(uri, node),
            condition=Expr.from_cst(uri, condition),
            consequence=Expr.from_cst(uri, consequence),
            alternative=head_or_none(
                Expr.from_cst(uri, alternative) for alternative in maybe_alternative
            ),
        )

    AST.register(from_cst, "conditional")


@D.dataclass
class Unknown(Expr):
    @staticmethod
    def from_cst(uri: URI, node: T.Node) -> "Unknown":
        return Unknown(location_of(uri, node))


@D.dataclass
class ErrorAST(Expr):
    node_type: str

    @staticmethod
    def from_cst(uri: URI, node: T.Node) -> "ErrorAST":
        return ErrorAST(location_of(uri, node), node.type)


@D.dataclass
class ErrorExpr(Expr):
    node_type: str

    @staticmethod
    def from_cst(uri: URI, node: T.Node) -> "ErrorExpr":
        return ErrorExpr(location_of(uri, node), node.type)


def position_of(point: T.Point) -> L.Position:
    return L.Position(point.row, point.column)


def range_of(node: T.Node) -> L.Range:
    return L.Range(
        position_of(node.range.start_point),
        position_of(node.range.end_point),
    )


def location_of(uri: URI, node: T.Node) -> L.Location:
    return L.Location(uri, range_of(node))


def range_contains(outer: L.Range, inner: L.Range):
    return outer.start <= inner.start and inner.end <= outer.end


RangeLike = L.Range | T.Range | T.Node | AST


def merge_ranges(lhs: RangeLike, rhs: RangeLike) -> L.Range:
    match lhs:
        case L.Range():
            start = lhs.start
        case T.Range() as r:
            start = position_of(r.start_point)
        case T.Node() as n:
            start = position_of(n.start_point)
        case AST():
            start = lhs.location.range.start

    match rhs:
        case L.Range():
            end = rhs.end
        case T.Range() as r:
            end = position_of(r.end_point)
        case T.Node() as n:
            end = position_of(n.end_point)
        case AST():
            end = rhs.location.range.end

    assert start < end or end == start

    return L.Range(start, end)


LocationLike = L.Location | AST


def merge_locations(lhs: LocationLike, rhs: LocationLike) -> L.Location:
    if isinstance(lhs, AST):
        lhs = lhs.location

    if isinstance(rhs, AST):
        rhs = rhs.location

    assert lhs.uri == rhs.uri, dedent(
        f"""\
        Cannot merge two locations from different documents:
        * {lhs.uri}
        * {rhs.uri}
        """
    )

    return L.Location(lhs.uri, merge_ranges(lhs.range, rhs.range))


@D.dataclass
class Binding:
    scope: "Scope"
    name: str
    location: L.Location
    bound_to: AST


@D.dataclass
class Scope:
    owner: AST
    bindings: list[Binding] = D.field(default_factory=list)
    parent: "Scope | None" = None
    children: list["Scope"] = D.field(default_factory=list)

    def bind_var(self, var: Id.Var, to: AST):
        self._bind(var.name, var.location, to)

    def bind_field(self, key: FixedKey, to: Field):
        self._bind(key.name, key.location, to)

    def _bind(self, name: str, location: L.Location, to: AST):
        self.bindings.insert(0, Binding(self, name, location, to))

    def get(self, name: str) -> Binding | None:
        return next(
            iter(b for b in self.bindings if b.name == name),
            None if self.parent is None else self.parent.get(name),
        )

    def nest(self, owner: AST) -> "Scope":
        child = Scope(owner, [], parent=self)
        self.children.append(child)
        return child

    @property
    def pretty_tree(self) -> str:
        return str(PrettyScope(self))

    @staticmethod
    def empty(owner: AST) -> "Scope":
        return Scope(owner)


@D.dataclass
class PrettyScope(PrettyTree):
    """A class for pretty-printing a scope."""

    node: Any
    label: str | None = None

    def node_text(self) -> str:
        match self.node:
            case Scope():
                repr = "Scope"
            case Binding(_, name, _, None):
                repr = name
            case Binding(_, name, _, AST() as bound_to):
                bound_to_class = bound_to.__class__.__qualname__
                bound_to_range = bound_to.location.range
                repr = f'"{name}" <- {bound_to_class} @ {bound_to_range}'
            case []:
                repr = "[]"
            case list():
                repr = "[...]"
            case AST() as owner:
                repr = f"{owner.__class__.__qualname__} [{owner.location.range}]"
            case _:
                repr = str(self.node)

        return repr if self.label is None else f"{self.label}={repr}"

    def children(self) -> list["PrettyTree"]:
        match self.node:
            case Scope(owner, bindings, _, children):
                return [
                    PrettyScope(owner, "owner"),
                    PrettyScope(bindings, "bindings"),
                    PrettyScope(children, "children"),
                ]
            case list() as array:
                return [PrettyScope(value, f"[{i}]") for i, value in enumerate(array)]
            case _:
                return []

    def __repr__(self):
        return super().__repr__()
