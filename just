#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#   "pygls",
#   "rich",
#   "tree-sitter",
#   "tree-sitter-language-pack",
#   "typer",
# ]
# ///

import logging
import unittest
from dataclasses import dataclass
from enum import StrEnum
from textwrap import dedent
from typing import Callable, Type, TypeVar, cast

import lsprotocol.types as L
import tree_sitter as T
import typer
from pygls.lsp.server import LanguageServer
from tree_sitter_language_pack import get_language, get_parser

app = typer.Typer(
    no_args_is_help=True,
    rich_markup_mode="markdown",
)

logging.basicConfig(
    filename="pygls.log",
    filemode="w",
    level=logging.DEBUG,
)

ExprType = TypeVar("ExprType")


@dataclass
class Expr:
    range: L.Range

    @staticmethod
    def from_tree(node: T.Node) -> "Expr":
        dispatch: dict[str, Callable[[T.Node], "Expr"]] = {
            "array": Array.from_tree,
            "binary": Binary.from_tree,
            "document": Document.from_tree,
            "false": Bool.from_tree,
            "forloop": ListComp.from_tree,
            "id": Id.from_tree,
            "local_bind": Local.from_tree,
            "number": Num.from_tree,
            "string": Str.from_tree,
            "true": Bool.from_tree,
        }

        return dispatch[node.type](node)

    def to(self, expect_type: Type[ExprType]) -> ExprType:
        if not isinstance(self, expect_type):
            raise TypeError(
                f"Expected {expect_type.__name__}, but got {type(self).__name__}"
            )

        return cast(ExprType, self)

    def bin_op(self, op: "Operator", rhs: "Expr") -> "Binary":
        range = L.Range(self.range.start, rhs.range.end)
        return Binary(range, op, self, rhs)

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

    def __eq__(self, rhs: "Expr") -> "Binary":
        return self.bin_op(Operator.Eq, rhs)

    def __ne__(self, rhs: "Expr") -> "Binary":
        return self.bin_op(Operator.NotEq, rhs)


@dataclass
class Document(Expr):
    body: Expr

    @staticmethod
    def from_tree(node: T.Node) -> "Document":
        assert node.type == "document"
        return Document(
            range=lsp_range_of(node),
            body=Expr.from_tree(node.named_children[0]),
        )


@dataclass
class Id(Expr):
    name: str

    @staticmethod
    def from_tree(node: T.Node) -> "Id":
        assert node.type == "id"
        assert node.text is not None

        return Id(
            range=lsp_range_of(node),
            name=node.text.decode(),
        )

    def bind(self, value: Expr) -> "Bind":
        range = L.Range(self.range.start, value.range.end)
        return Bind(range, self, value)


@dataclass
class Num(Expr):
    value: float

    @staticmethod
    def from_tree(node: T.Node) -> "Num":
        assert node.type == "number"
        assert node.text is not None

        return Num(
            range=lsp_range_of(node),
            value=float(node.text.decode()),
        )


@dataclass
class Str(Expr):
    raw: str

    @staticmethod
    def from_tree(node: T.Node) -> "Str":
        assert node.type == "string"

        _, content, _ = node.named_children
        assert content.text is not None

        return Str(
            range=lsp_range_of(node),
            # The raw string content before escaping or indentations are handled.
            raw=content.text.decode(),
        )


@dataclass
class Bool(Expr):
    value: bool

    @staticmethod
    def from_tree(node: T.Node) -> "Bool":
        assert node.type in ["true", "false"]
        assert node.text is not None

        return Bool(
            range=lsp_range_of(node),
            value=node.text.decode() == "true",
        )


@dataclass
class Array(Expr):
    values: list[Expr]

    @staticmethod
    def from_tree(node: T.Node) -> "Array":
        assert node.type == "array"
        return Array(
            range=lsp_range_of(node),
            values=[Expr.from_tree(c) for c in node.named_children],
        )


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


@dataclass
class Binary(Expr):
    op: Operator
    lhs: Expr
    rhs: Expr

    @staticmethod
    def from_tree(node: T.Node) -> "Binary":
        assert node.type == "binary"

        lhs, op, rhs = node.named_children
        assert op.text is not None

        return Binary(
            range=lsp_range_of(node),
            op=Operator(op.text.decode("utf-8")),
            lhs=Expr.from_tree(lhs),
            rhs=Expr.from_tree(rhs),
        )


@dataclass
class Bind:
    range: L.Range
    id: Id
    value: Expr

    @staticmethod
    def from_tree(node: T.Node) -> "Bind":
        assert node.type == "bind"
        [id, value] = node.named_children

        return Bind(
            range=L.Range(
                lsp_position_of(id.range.start_point),
                lsp_position_of(value.range.end_point),
            ),
            id=Expr.from_tree(id).to(Id),
            value=Expr.from_tree(value),
        )


@dataclass
class Local(Expr):
    binds: list[Bind]
    body: Expr

    @staticmethod
    def from_tree(node: T.Node) -> "Local":
        assert node.type == "local_bind"
        _, *binds, expr = node.named_children

        return Local(
            range=lsp_range_of(node),
            binds=[Bind.from_tree(b) for b in binds],
            body=Expr.from_tree(expr),
        )


@dataclass
class ForSpec:
    range: L.Range
    id: Id
    expr: Expr

    @staticmethod
    def from_tree(node: T.Node) -> "ForSpec":
        assert node.type == "forspec"
        id, expr = node.named_children

        return ForSpec(
            lsp_range_of(node),
            Id.from_tree(id),
            Expr.from_tree(expr),
        )


@dataclass
class IfSpec:
    range: L.Range
    condition: Expr

    @staticmethod
    def from_tree(node: T.Node) -> "IfSpec":
        assert node.type == "ifspec"
        [condition] = node.named_children

        return IfSpec(
            lsp_range_of(node),
            Expr.from_tree(condition),
        )


@dataclass
class ListComp(Expr):
    expr: Expr
    for_spec: ForSpec
    comp_spec: list[ForSpec | IfSpec]

    @staticmethod
    def from_tree(node: T.Node) -> "ListComp":
        if len(node.named_children) == 2:
            expr, for_spec = node.named_children
            comp_spec = []
        else:
            expr, for_spec, comp_spec = node.named_children
            comp_spec = comp_spec.named_children

        return ListComp(
            range=lsp_range_of(node),
            expr=Expr.from_tree(expr),
            for_spec=ForSpec.from_tree(for_spec),
            comp_spec=[
                ForSpec.from_tree(spec)
                if spec.type == "forspec"
                else IfSpec.from_tree(spec)
                for spec in comp_spec
            ],
        )


def lsp_position_of(point: T.Point) -> L.Position:
    return L.Position(point.row, point.column)


def lsp_range_of(node: T.Node) -> L.Range:
    return L.Range(
        lsp_position_of(node.range.start_point),
        lsp_position_of(node.range.end_point),
    )


server = LanguageServer("pj", "v0.1")


def parse(source: str) -> T.Node:
    return get_parser("jsonnet").parse(source.encode("utf-8")).root_node


def document_root(uri: str) -> T.Node:
    return parse(server.workspace.get_text_document(uri).source)


@server.feature(L.TEXT_DOCUMENT_COMPLETION)
def completions(params: L.CompletionParams):
    root_node = document_root(params.text_document.uri)
    query = T.Query(
        get_language("jsonnet"),
        dedent(
            """\
            (local_bind
              (bind (id) @local-bind.function
                    (params)))

            (local_bind
              (bind (id) @local-bind.variable
                    !params))

            (field
              (fieldname (id) @field.function)
              (params))

            (field
              (fieldname (id) @field)
              !params)
            """,
        ),
    )

    captures = T.QueryCursor(query).captures(root_node)

    def completion_items():
        patterns = {
            "local-bind.variable": L.CompletionItemKind.Variable,
            "local-bind.function": L.CompletionItemKind.Function,
            "field.function": L.CompletionItemKind.Method,
            "field": L.CompletionItemKind.Field,
        }

        for capture, kind in patterns.items():
            for node in captures.get(capture, []):
                if node.text is not None:
                    text = node.text.decode("utf-8")
                    yield L.CompletionItem(label=text, kind=kind)

    return L.CompletionList(
        is_incomplete=False,
        items=list(completion_items()),
    )


class TestDocument:
    def __init__(self, source: str) -> None:
        self.lines = source.splitlines(keepends=False)
        self.body = Document.from_tree(parse(source)).body

    def start_of(self, needle: str, line=1, nth=1) -> L.Position:
        assert line >= 1 and nth >= 1

        line -= 1
        nth -= 1

        character = self.lines[line].find(needle)
        assert character >= 0

        while nth > 0:
            nth -= 1
            character = self.lines[line].find(needle, character + len(needle))
            assert character >= 0

        return L.Position(line, character)

    def end_of(self, needle: str, line=1, nth=1) -> L.Position:
        pos = self.start_of(needle, line, nth)
        pos.character += len(needle)
        return pos

    def range_of(self, needle: str, line=1, nth=1) -> L.Range:
        start = self.start_of(needle, line, nth)
        end = L.Position(start.line, start.character + len(needle))
        return L.Range(start, end)

    def id(self, name: str, line=1, nth=1) -> Id:
        return Id(self.range_of(name, line, nth), name)

    def boolean(self, value: bool, line=1, nth=1) -> Bool:
        needle = "true" if value else "false"
        range = self.range_of(needle, line, nth)
        return Bool(range, value)

    def num(self, value: float | int, literal: str | None = None, line=1, nth=1) -> Num:
        match value, literal:
            case int(), None:
                literal = str(value)
            case _:
                pass

        return Num(self.range_of(literal, line, nth), value)

    def str(self, value: str, literal: str, line=1, nth=1) -> Str:
        return Str(self.range_of(literal, line, nth), value)


class TestAST(unittest.TestCase):
    def test_number(self):
        t = TestDocument("1")

        self.assertEqual(
            t.body,
            t.num(1),
        )

    def test_string(self):
        for literal, expected in [
            ("'hello\\nworld'", "hello\\nworld"),
            ('"hello\\nworld"', "hello\\nworld"),
            ("@'hello\\nworld'", "hello\\nworld"),
            ('@"hello\\nworld"', "hello\\nworld"),
            ("|||\n  hello\n|||", "\n  hello\n"),
        ]:
            t = TestDocument(literal)
            self.assertEqual(
                t.body,
                Str(t.body.range, expected),
            )

    def test_local(self):
        t = TestDocument("local x = 1; x")

        self.assertEqual(
            t.body,
            Local(
                range=t.body.range,
                binds=[t.id("x").bind(t.num(1))],
                body=t.id("x", nth=2),
            ),
        )

    def test_local_multi_binds(self):
        t = TestDocument(
            dedent(
                """\
                local x = 1, y = 2;
                x + y
                """
            )
        )

        self.assertEqual(
            t.body,
            Local(
                range=t.body.range,
                binds=[
                    t.id("x").bind(t.num(1)),
                    t.id("y").bind(t.num(2)),
                ],
                body=t.id("x", line=2) + t.id("y", line=2),
            ),
        )

    def test_empty_array(self):
        t = TestDocument("[]")

        self.assertEqual(
            t.body,
            Array(range=t.body.range, values=[]),
        )

    def test_array(self):
        t = TestDocument("[1, true, '3']")

        self.assertEqual(
            t.body,
            Array(
                range=t.body.range,
                values=[
                    t.num(1),
                    t.boolean(True),
                    t.str("3", literal="'3'"),
                ],
            ),
        )

    def test_binary(self):
        for op in Operator:
            t = TestDocument(f"a {op.value} b")

            self.assertEqual(
                t.body,
                t.id("a").bin_op(op, t.id("b")),
            )

    def test_binary_precedences(self):
        t = TestDocument("a + b * c")

        self.assertEqual(
            t.body,
            t.id("a") + t.id("b") * t.id("c"),
        )

    def test_list_comp(self):
        t = TestDocument("[x for x in [1, 2] if x > 1]")

        self.assertEqual(
            t.body,
            ListComp(
                range=t.body.range,
                expr=t.id("x"),
                for_spec=ForSpec(
                    range=t.range_of("for x in [1, 2]"),
                    id=t.id("x", nth=2),
                    expr=Array(
                        range=t.range_of("[1, 2]"),
                        values=[
                            t.num(1),
                            t.num(2),
                        ],
                    ),
                ),
                comp_spec=[
                    IfSpec(
                        range=t.range_of("if x > 1"),
                        condition=t.id("x", nth=3) > t.num(1, nth=2),
                    ),
                ],
            ),
        )


@app.command()
def serve():
    server.start_io()


@app.command()
def test():
    unittest.main(argv=["--verbose", "--locals"])


if __name__ == "__main__":
    app()

# vim:ft=python tw=88
