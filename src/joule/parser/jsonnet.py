import bisect
from functools import partial, reduce
from itertools import accumulate, chain
from typing import Any, Sequence

from parsimonious import NodeVisitor
from parsimonious import expressions as E
from parsimonious.nodes import Node
from parsy import Callable

from joule import ast as A
from joule.grammar import load_grammar

from .string import StringParser

JSONNET_GRAMMAR = load_grammar("jsonnet.grammar")


def parse_jsonnet(uri: A.URI, source: str, rule: str = "primary") -> A.AST:
    root = JSONNET_GRAMMAR.default(rule).parse(source)
    return JsonnetParser(uri, root).visit(root)


PostfixBuilder = Callable[[A.Anchor, A.AST], A.AST]


class LineMap:
    def __init__(self, text: str) -> None:
        self.text = text

        # Computes the character offset of the first character in each line, used for
        # conversions between 2D points and 1D offsets.
        #
        # NOTE: An LSP range is a half-open intervals `[start, end)`. All text lines but
        # the last end with a newline. Adding an EOF "\0" helps simplify computing the
        # line offsets array.
        lines = (text + "\0").splitlines(keepends=True)
        self.line_offsets: list[int] = list(accumulate(chain([0], map(len, lines))))

    def point_of(self, offset: int) -> A.Point:
        line = bisect.bisect_right(self.line_offsets, offset) - 1
        column = offset - self.line_offsets[line]
        return A.Point(line=line, character=column)

    def offset_of(self, point: A.Point) -> int:
        return self.line_offsets[point.line] + point.character


class JsonnetParser(NodeVisitor, LineMap):
    def __init__(self, uri: A.URI, node: Node):
        LineMap.__init__(self, node.full_text)
        self.uri = uri

    def start_of(self, node: Node) -> A.Point:
        return self.point_of(node.start)

    def end_of(self, node: Node) -> A.Point:
        return self.point_of(node.end)

    def span_of(self, node: Node) -> A.Span:
        return A.Span(self.start_of(node), self.end_of(node))

    def anchor_of(self, node: Node) -> A.Anchor:
        return A.Anchor(self.uri, self.span_of(node))

    def generic_visit(self, node: Node, visited_children: Sequence[Any]):
        return visited_children[0] if isinstance(node.expr, E.OneOf) else node

    @staticmethod
    def build_id(fn: Callable[[A.Anchor, str], A.AST]):
        def visit(self, node: Node, children: Sequence[Node]):
            del node
            _, id, *_ = children
            return fn(self.anchor_of(id), id.text)

        return visit

    visit_field_id = build_id(A.Id.Field)
    visit_field_ref_id = build_id(A.Id.FieldRef)
    visit_param_ref_id = build_id(A.Id.ParamRef)
    visit_var_id = build_id(A.Id.Var)
    visit_var_ref_id = build_id(A.Id.VarRef)

    def visit_binary_literal(self, node: Node, _: Sequence[Any]):
        return A.Num(self.anchor_of(node), float(int(node.text[2:], base=2)))

    def visit_boolean(self, node: Node, _: Sequence[Any]):
        return A.Bool(self.anchor_of(node), node.text == "true")

    def visit_decimal_literal(self, node: Node, _: Sequence[Any]):
        return A.Num(self.anchor_of(node), float(node.text))

    def visit_dollar(self, node: Node, _: Sequence[Any]):
        return A.Dollar(self.anchor_of(node))

    def visit_field_access(self, node: Node, children: Sequence[Any]):
        _, _, _, field_ref = children
        return (self.point_of(node.end), partial(A.FieldAccess, field=field_ref))

    def visit_hexical_literal(self, node: Node, _: Sequence[Any]):
        return A.Num(self.anchor_of(node), float(int(node.text[2:], base=16)))

    def visit_inline_string(self, node: Node, _: Sequence[Any]):
        return A.Str(self.anchor_of(node), StringParser.parse_inline_string(node.text))

    def visit_null(self, node: Node, _: Sequence[Any]):
        return A.Null(self.anchor_of(node))

    def visit_octal_literal(self, node: Node, _: Sequence[Any]):
        return A.Num(self.anchor_of(node), float(int(node.text[2:], base=8)))

    def visit_postfix(self, node: Node, children: Sequence[Any]):
        start = self.start_of(node)
        primary, ops = children

        def build(lhs: A.AST, op: tuple[A.Point, PostfixBuilder]) -> A.AST:
            end, fn = op
            anchor = A.Anchor(self.uri, A.Span(start, end))
            return fn(anchor, lhs)

        return reduce(build, ops, primary)

    def visit_postfix_ops(self, _: Node, children: Sequence[Any]):
        return children

    def visit_self(self, node: Node, _: Sequence[Any]):
        return A.Self(self.anchor_of(node))

    def visit_super(self, node: Node, _: Sequence[Any]):
        return A.Super(self.anchor_of(node))

    def visit_text_block(self, node: Node, _: Sequence[Any]):
        return A.Str(self.anchor_of(node), StringParser.parse_text_block(node.text))

    def visit_unary_with_op(self, _: Node, children: Sequence[Any]):
        match children:
            case (A.Span() as op_span, A.UnaryOp() as op), _, A.Expr() as operand:
                return A.Unary(operand.anchor.merge(op_span), op, operand)

    def visit_unary_op(self, _: Node, children: Sequence[Any]):
        op = children[0]
        return self.span_of(op), A.UnaryOp(op.text)
