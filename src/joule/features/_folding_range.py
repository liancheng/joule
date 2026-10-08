from typing import override

import lsprotocol.types as L

from joule.syntax import trees as T
from joule.syntax.visitor import Visitor


class FoldingRangeProvider(Visitor):
    folding_ranges: list[L.FoldingRange]

    def __init__(self):
        self.folding_ranges = []

    def serve(self, doc: T.Document) -> list[L.FoldingRange]:
        self.visit(doc)
        return self.folding_ranges

    def add_folding_range(self, span: T.Span):
        if span.start.line != span.end.line:
            self.folding_ranges.append(
                L.FoldingRange(
                    start_line=span.start.line,
                    start_character=span.start.column,
                    end_line=span.end.line,
                    end_character=span.end.column,
                )
            )

    @override
    def visit_array(self, t: T.Array):
        super().visit_array(t)
        self.add_folding_range(t.span)

    @override
    def visit_array_comp(self, t: T.ArrayComp):
        super().visit_array_comp(t)
        self.add_folding_range(t.span)

    @override
    def visit_fn(self, t: T.Fn):
        super().visit_fn(t)
        self.add_folding_range(t.span)

    @override
    def visit_obj_comp(self, t: T.ObjComp):
        super().visit_obj_comp(t)
        self.add_folding_range(t.span)

    @override
    def visit_object(self, t: T.Object):
        super().visit_object(t)
        self.add_folding_range(t.span)

    @override
    def visit_paren(self, t: T.Paren):
        super().visit_paren(t)
        self.add_folding_range(t.span)
