import dataclasses as D
from copy import copy
from enum import Enum, StrEnum, auto
from textwrap import dedent, shorten
from typing import (
    Annotated,
    Any,
    Iterable,
    Type,
    TypeVar,
)

import lsprotocol.types as L

from joule.maybe import head_or_none, maybe
from joule.pretty import PrettyTree

URI = Annotated[str, "URI"]


AstType = TypeVar("AstType", bound="AST")


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

    def __repr__(self) -> str:
        return f"{self.start!r}-{self.end!r}"

    def contains(self, other: Point | Span) -> bool:
        if isinstance(other, Point):
            other = Span(other, other)
        return self.start <= other.start and other.end <= self.end

    def merge(self, other: Span) -> Span:
        return Span(
            self.start if self.start <= other.start else other.start,
            self.end if self.end >= other.end else other.end,
        )


@D.dataclass(frozen=True)
class Anchor:
    uri: URI
    span: Span

    @staticmethod
    def from_lsp(location: L.Location):
        return Anchor(location.uri, Span.from_lsp(location.range))

    @property
    def lsp(self) -> L.Location:
        return L.Location(self.uri, self.span.lsp)

    def __repr__(self) -> str:
        return f"{self.uri}:{self.span!r}"

    def merge(self, other: Anchor | Span) -> Anchor:
        if isinstance(other, Anchor):
            assert self.uri == other.uri, dedent(
                f"""\
                Cannot merge locations from different documents:
                * {self.uri}
                * {other.uri}
                """
            )
            other = other.span

        return Anchor(self.uri, self.span.merge(other))


@D.dataclass
class AST:
    anchor: Anchor

    def __post_init__(self):
        self.parent: AST | None = None

        for child in self.children:
            child.parent = self

    def to(self, expect_type: Type[AstType]) -> AstType:
        if not isinstance(self, expect_type):
            raise TypeError(
                f"Expected {expect_type.__qualname__}, but got {type(self).__qualname__}"
            )

        return self

    @property
    def children(self) -> Iterable[AST]:
        return []

    @property
    def pretty(self) -> str:
        return str(PrettyAST(self))

    def node_at(self, target: Point | Span) -> AST | None:
        """Returns the narrowest AST node covering the target location."""
        if isinstance(target, Point):
            target = Span(target, target)

        candidate = head_or_none(
            node
            for child in self.children
            if child.anchor.span.contains(target)
            for node in maybe(child.node_at(target))
        )

        match candidate:
            case None if self.anchor.span.contains(target):
                return self
            case None:
                return None
            case node:
                return node

    def find_ancestor(
        self,
        expected_type: type[AstType],
        *,
        level: int | None = None,
    ) -> AstType | None:
        def find(node: AST | None, level: int | None = None) -> AstType | None:
            match node, level:
                case None, _:
                    return None
                case _, -1:
                    return None
                case _ if isinstance(node, expected_type):
                    return node
                case _, None:
                    return find(node.parent, None)
                case _, int():
                    return find(node.parent, level - 1)

        return find(self, level)


@D.dataclass
class Expr(AST):
    def __post_init__(self):
        super().__post_init__()

        # Tracks expressions whose tails contain this expression.
        self.tail_of = []

        for tail in self.tails:
            if tail is not self:
                tail.tail_of.append(self)

    @property
    def tails(self) -> Iterable[Expr]:
        """Tail expressions of this expression.

        A tail of an expression decides the value the expression returns. Simple
        expressions like literal values and variable references are their own tails.
        More complex expressions may have more than one tail due to branching.

         1. Single tail expressions:

            ```plaintext
            42
            ^^
            local val = 1; val
                           ^^^
            assert cond; val
                         ^^^
            ```

         2. Multi-tail expression:

            ```plaintext
            if cond then val1 else val2
                         ^^^^      ^^^^
            ```

        Tails are recursive. `val1` and `val2` below are tails of both the inner `if`
        expression and the top-level `local` expression, but the `if` expression is
        _not_ a tail of the `local` expression.

            ```plaintext
            local cond = f(); if cond then val1 else val2
                                           ^^^^      ^^^^
            ```
        """
        return [self]


@D.dataclass
class Null(Expr):
    pass


@D.dataclass
class Dollar(Expr):
    pass


@D.dataclass
class Self(Expr):
    pass


@D.dataclass
class Super(Expr):
    pass


class AnalysisPhase(Enum):
    Unresolved = auto()
    ScopeResolved = auto()


@D.dataclass
class Document(Expr):
    body: Expr

    def __post_init__(self):
        super().__post_init__()
        self.analysis_phase = AnalysisPhase.Unresolved
        self.top_level_scope: VarScope | None = None
        self.importees: list[Importee] = []
        self.field_refs: list[Id.FieldRef] = []
        self.calls: list[Call] = []

    @property
    def children(self) -> Iterable[AST]:
        return [self.body]

    @property
    def tails(self) -> Iterable[Expr]:
        return self.body.tails


class Id:
    @D.dataclass
    class Var(Expr):
        name: str

        def __post_init__(self):
            super().__post_init__()
            self.binding: VarBinding | None = None
            self.references: list[Id.VarRef] = []

    @D.dataclass
    class VarRef(Expr):
        name: str

        def __post_init__(self):
            super().__post_init__()
            self.var: Id.Var | None = None

    @D.dataclass
    class Field(Expr):
        name: str

        def __post_init__(self):
            super().__post_init__()
            self.binding: FieldBinding | None = None

        @staticmethod
        def from_string(string: Str) -> Id.Field:
            return Id.Field(string.anchor, string.value)

    @D.dataclass
    class FieldRef(Expr):
        name: str

    @D.dataclass
    class ParamRef(Expr):
        name: str


@D.dataclass
class Num(Expr):
    value: float


@D.dataclass
class Str(Expr):
    value: str


@D.dataclass
class Bool(Expr):
    value: bool


@D.dataclass
class Array(Expr):
    values: list[Expr]

    @property
    def children(self) -> Iterable[AST]:
        return iter(value for value in self.values)


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


class UnaryOp(StrEnum):
    Plus = "+"
    Negate = "-"
    Not = "!"
    BitNot = "~"


@D.dataclass
class Unary(Expr):
    op: UnaryOp
    operand: Expr

    @property
    def children(self) -> Iterable[AST]:
        return [self.operand]


@D.dataclass
class Binary(Expr):
    op: BinaryOp
    lhs: Expr
    rhs: Expr

    @property
    def children(self) -> Iterable[AST]:
        return [self.lhs, self.rhs]


@D.dataclass
class Bind(AST):
    id: Id.Var
    value: Expr

    @property
    def children(self) -> Iterable[AST]:
        return [self.id, self.value]


@D.dataclass
class Local(Expr):
    binds: list[Bind]
    body: Expr

    @property
    def tails(self) -> Iterable[Expr]:
        return self.body.tails

    @property
    def children(self) -> Iterable[AST]:
        yield from self.binds
        yield self.body


@D.dataclass
class Param(AST):
    id: Id.Var
    default: Expr | None = None

    @property
    def children(self) -> Iterable[AST]:
        yield self.id
        yield from maybe(self.default)


@D.dataclass
class Fn(Expr):
    params: list[Param]
    body: Expr

    @property
    def children(self) -> Iterable[AST]:
        yield from self.params
        yield self.body


@D.dataclass
class Arg(AST):
    value: Expr
    id: Id.ParamRef | None = None

    @property
    def children(self) -> Iterable[AST]:
        yield self.value
        yield from maybe(self.id)


@D.dataclass
class Call(Expr):
    callee: Expr
    args: list[Arg]

    @property
    def children(self) -> Iterable[AST]:
        yield self.callee
        yield from self.args

    def arg_by_name(self, name: str) -> Expr | None:
        return head_or_none(
            arg.value for arg in self.args for id in maybe(arg.id) if id.name == name
        )

    def arg_by_position(self, index: int) -> Expr | None:
        return self.args[index].value if 0 <= index < len(self.args) else None

    def arg_of_param(self, param: Param) -> Expr | None:
        return self.arg_by_name(param.id.name) or head_or_none(
            self.args[param_ord].value
            for fn in maybe(param.find_ancestor(Fn, level=1))
            if (param_ord := fn.params.index(param)) >= 0
            if (param_ord < len(self.args))
        )


@D.dataclass
class ForSpec(AST):
    id: Id.Var
    source: Expr

    @property
    def children(self) -> Iterable[AST]:
        return [self.id, self.source]


@D.dataclass
class IfSpec(AST):
    condition: Expr

    @property
    def children(self) -> Iterable[AST]:
        return [self.condition]


CompSpec = list[ForSpec | IfSpec]


@D.dataclass
class ListComp(Expr):
    expr: Expr
    for_spec: ForSpec
    comp_spec: CompSpec

    @property
    def children(self) -> Iterable[AST]:
        yield self.expr
        yield self.for_spec
        yield from self.comp_spec


class ImportType(StrEnum):
    Default = "import"
    Str = "importstr"
    Bin = "importbin"


@D.dataclass
class Importee(Str):
    pass

    @staticmethod
    def from_string(string: Str) -> Importee:
        return Importee(string.anchor, string.value)


@D.dataclass(frozen=True)
class ImporteeKey:
    uri: URI
    path: str

    @classmethod
    def of(cls, origin: Importee) -> ImporteeKey:
        return cls(origin.anchor.uri, origin.value)


@D.dataclass
class Import(Expr):
    type: ImportType
    importee: Importee

    @property
    def children(self) -> Iterable[AST]:
        return [self.importee]


@D.dataclass
class Assert(AST):
    condition: Expr
    message: Expr | None = None

    @property
    def children(self) -> Iterable[AST]:
        yield self.condition
        yield from maybe(self.message)


@D.dataclass
class AssertExpr(Expr):
    assertion: Assert
    body: Expr

    @property
    def tails(self) -> Iterable[Expr]:
        return self.body.tails

    @property
    def children(self) -> Iterable[AST]:
        return [self.assertion, self.body]


class Visibility(StrEnum):
    Default = ":"
    Hidden = "::"
    Forced = ":::"


@D.dataclass
class FieldKey(AST):
    pass


@D.dataclass
class FixedKey(FieldKey):
    id: Id.Field

    @property
    def children(self) -> Iterable[AST]:
        return [self.id]


@D.dataclass
class ComputedKey(FieldKey):
    expr: Expr

    @property
    def children(self) -> Iterable[AST]:
        return [self.expr]


@D.dataclass
class Field(AST):
    key: FieldKey
    value: Expr
    visibility: Visibility = Visibility.Default
    inherited: bool = False

    @property
    def children(self) -> Iterable[AST]:
        return [self.key, self.value]


@D.dataclass
class Object(Expr):
    binds: list[Bind] = D.field(default_factory=list)
    asserts: list[Assert] = D.field(default_factory=list)
    fields: list[Field] = D.field(default_factory=list)

    def __post_init__(self):
        super().__post_init__()
        self.field_scope: FieldScope | None = None

    @property
    def children(self) -> Iterable[AST]:
        yield from self.binds
        yield from self.asserts
        yield from self.fields

    @classmethod
    def has_field_scope(cls) -> bool:
        return True


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
        yield self.field
        yield from self.binds
        yield from self.asserts
        yield self.for_spec
        yield from self.comp_spec


@D.dataclass
class FieldAccess(Expr):
    obj: Expr
    field: Id.FieldRef

    @property
    def children(self) -> Iterable[AST]:
        return [self.obj, self.field]


@D.dataclass
class Slice(Expr):
    array: Expr
    begin: Expr | None = None
    end: Expr | None = None
    step: Expr | None = None

    @property
    def children(self) -> Iterable[AST]:
        yield self.array
        yield from maybe(self.begin)
        yield from maybe(self.end)
        yield from maybe(self.step)


@D.dataclass
class If(Expr):
    condition: Expr
    consequence: Expr
    alternative: Expr | None = None

    @property
    def tails(self) -> Iterable[Expr]:
        yield from self.consequence.tails
        yield from (
            tail
            for alternative in maybe(self.alternative)
            for tail in alternative.tails
        )

    @property
    def children(self) -> Iterable[AST]:
        yield self.condition
        yield self.consequence
        yield from maybe(self.alternative)

    @property
    def branches(self) -> Iterable[Expr]:
        return (
            [self.consequence, self.alternative]
            if self.alternative
            else [self.consequence]
        )


@D.dataclass
class VarBinding:
    scope: VarScope
    id: Id.Var | Id.Field
    target: AST


@D.dataclass
class VarScope:
    owner: AST
    bindings: list[VarBinding] = D.field(default_factory=list)
    parent: VarScope | None = None
    children: list[VarScope] = D.field(default_factory=list)

    def bind(self, var: Id.Var, to: AST):
        var.binding = VarBinding(self, var, to)
        self.bindings.insert(0, var.binding)

    def get(self, name: str) -> VarBinding | None:
        return next(
            iter(b for b in self.bindings if b.id.name == name),
            None if self.parent is None else self.parent.get(name),
        )

    def nest(self, owner: AST) -> VarScope:
        child = VarScope(owner, [], parent=self)
        self.children.append(child)
        return child

    @staticmethod
    def empty(owner: AST) -> VarScope:
        return VarScope(owner)


@D.dataclass
class FieldBinding:
    scope: FieldScope
    id: Id.Field
    target: Field


@D.dataclass
class FieldScope:
    owner: Object
    bindings: list[FieldBinding] = D.field(default_factory=list)
    parent: FieldScope | None = None
    children: list[FieldScope] = D.field(default_factory=list)

    def bind(self, key: FixedKey, to: Field):
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

    def copy_with_child(self, child: FieldScope) -> FieldScope:
        new_self = copy(self)
        new_self.children = copy(self.children)
        new_child = copy(child)

        new_self.children.append(new_child)
        new_child.parent = new_self

        return new_child

    @staticmethod
    def empty(owner: Object) -> FieldScope:
        return FieldScope(owner)


@D.dataclass
class PrettyAST(PrettyTree):
    """A class for pretty-printing a Jsonnet AST."""

    node: Any
    label: str | None = None

    def node_text(self) -> str:
        match self.node:
            case Document() as doc:
                # For the top-level `Document` node, prints the full location with URI.
                repr = f"{doc.__class__.__qualname__} [{doc.anchor}]"
            case AST() as ast:
                # For all other nodes, only prints the range.
                repr = f"{ast.__class__.__qualname__} [{ast.anchor.span}]"
            case _, *_:
                # For lists, print a placeholder as all the elements are printed
                # separately as child nodes.
                repr = "[...]"
            case str():
                # Escapes strings and truncates long ones.
                repr = shorten(f"{self.node!r}", width=20)
            case _:
                # Falls back to `__str__` for everything else.
                repr = str(self.node)

        # Prepends the label, if any.
        return repr if self.label is None else f"{self.label}={repr}"

    def children(self) -> list[PrettyTree]:
        match self.node:
            case AST() as ast:
                return [
                    PrettyAST(v, f.name)
                    for f, v in self.non_empty_fields(ast)
                    if f.name != "anchor"
                ]
            case list() as array if (size := len(array)) > 0:
                return [PrettyAST(array[i], f"[{i}]") for i in range(size)]
            case _:
                return []

    def __repr__(self):
        return super().__repr__()
