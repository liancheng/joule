from textwrap import dedent
from typing import Any, Sequence

from parsimonious import NodeVisitor
from parsimonious.expressions import OneOf
from parsimonious.nodes import Node

from joule.grammar import load_grammar

STRING_GRAMMAR = load_grammar("string.grammar")


def decode_codepoint(high: int, low: int | None) -> str:
    if 0xD800 <= high <= 0xDFFF:
        # High 16 bit as surrogate: non-BMP code point
        assert low is not None, "Invalid escaped non-BMP code point"
        return chr(0x10000 + (high - 0xD800) * 0x400 + (low - 0xDC00))
    elif low is None:
        # BMP code point
        return chr(high)
    else:
        return chr(high) + chr(low)


class StringParser(NodeVisitor):
    SIMPLE_ESC = dict(zip("\\/bnfrt'\"", "\\/\b\n\f\r\t'\""))

    @staticmethod
    def parse_inline_string(raw: str) -> str:
        root = STRING_GRAMMAR.default("inline_string").parse(raw)
        return StringParser().visit(root)

    @staticmethod
    def parse_text_block(raw: str) -> str:
        verbatim = raw.startswith("@")
        drop_last_newline = raw[1 if verbatim else 0 :].startswith("|||-")

        rule = "verbatim_text_block" if verbatim else "text_block"
        block = dedent("".join(raw.splitlines(keepends=True)[1:-1]))
        parsed = StringParser().visit(STRING_GRAMMAR.default(rule).parse(block))

        return parsed if drop_last_newline else parsed + "\n"

    def generic_visit(self, node: Node, visited_children: Sequence[Any]):
        return visited_children[0] if isinstance(node.expr, OneOf) else node

    def visit_simple_esc(self, node: Node, children: Sequence[Node]):
        del node
        _, char = children
        return self.SIMPLE_ESC[char.text]

    def visit_unicode_esc(self, _: Node, children: Sequence[Node]):
        _, code = children
        return int(code.text, base=16)

    def visit_low_surrogate(self, _: Node, children: Sequence[Node]):
        return next(iter(children), None)

    def visit_codepoint_esc(self, node: Node, children: Sequence[Any]):
        del node
        high, low = children
        return decode_codepoint(high, low)

    def visit_any(self, node: Node, _: Sequence[Any]):
        return node.text

    def build_quoted_any(self, _: Node, children: Sequence[Any]):
        _, char = children
        return char

    visit_single_quoted_any = build_quoted_any
    visit_double_quoted_any = build_quoted_any
    visit_verbatim_single_quoted_any = build_quoted_any
    visit_verbatim_double_quoted_any = build_quoted_any

    def visit_verbatim_single_quoted_esc(self, node: Node, _: Sequence[Any]):
        del node
        return "'"

    def visit_verbatim_double_quoted_esc(self, node: Node, _: Sequence[Any]):
        del node
        return '"'

    def build_content(self, _: Node, children: Sequence[str]):
        return "".join(children)

    visit_content = build_content
    visit_single_quoted_content = build_content
    visit_double_quoted_content = build_content
    visit_verbatim_single_quoted_content = build_content
    visit_verbatim_double_quoted_content = build_content

    def build_inline_string(self, node: Node, children: Sequence[str]):
        del node
        _, content, _ = children
        return content

    visit_single_quoted_string = build_inline_string
    visit_double_quoted_string = build_inline_string
    visit_verbatim_single_quoted_string = build_inline_string
    visit_verbatim_double_quoted_string = build_inline_string

    def visit_text_block_line(self, node: Node, children: Sequence[Any]):
        del node
        line, _ = children
        return line

    def visit_verbatim_text_block_line(self, node: Node, children: Sequence[Node]):
        del node
        line, _ = children
        return line.text

    def visit_text_block(self, _: Node, children: Sequence[Any]):
        return "\n".join(children)

    def visit_verbatim_text_block(self, _: Node, children: Sequence[Any]):
        return "\n".join(children)
