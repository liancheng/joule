import dataclasses as D
from collections.abc import Callable, Iterable
from enum import Enum, StrEnum
from typing import Any, ClassVar, TypeVar

import lsprotocol.types as L
import tree_sitter as ts
import tree_sitter_jsonnet

from joule.maybe import just
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

ts_parser = ts.Parser(ts.Language(tree_sitter_jsonnet.language()))


def strip_comments(nodes: Iterable[ts.Node]) -> Iterable[ts.Node]:
    return (node for node in nodes if node.type != "comment")


@D.dataclass
class Tree:
    span: Span

    registry: ClassVar[dict[str, FromCST]] = {}

    @staticmethod
    def register(fn: FromCST, *node_types: str):
        for node_type in node_types:
            assert node_type not in Tree.registry, f'"{node_type}" already registered.'
            Tree.registry[node_type] = fn

    @staticmethod
    def from_source(source: str) -> Tree:
        root = ts_parser.parse(source.encode()).root_node
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
        body, *_ = strip_comments(node.children)
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
        values = [Expr.from_cst(child) for child in strip_comments(node.named_children)]
        return Array(span_of(node), values)

    Tree.register(from_cst, "array")


class UnaryOp(StrEnum):
    Plus = "+"
    Negate = "-"
    Not = "!"
    BitNot = "~"


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


@D.dataclass
class Unary(Expr):
    op: UnaryOp
    operand: Expr

    @staticmethod
    def from_cst(node: ts.Node) -> Unary:
        assert node.type == "unary"
        op, operand, *_ = strip_comments(node.named_children)

        return Unary(
            span_of(node),
            op=UnaryOp(just(op.text).decode()),
            operand=Expr.from_cst(operand),
        )

    Tree.register(from_cst, "unary")


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
