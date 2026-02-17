import lsprotocol.types as L

from joule.ast import Array, Document, Fn, ListComp, ObjComp, Object
from joule.visitor import Visitor


class FoldingRangeProvider(Visitor):
    def __init__(self) -> None:
        self.folding_ranges: list[L.FoldingRange] = []

    def serve(self, tree: Document) -> list[L.FoldingRange]:
        self.visit(tree)
        return self.folding_ranges

    def _add_folding_range(self, span: L.Range):
        if span.start.line != span.end.line:
            self.folding_ranges.append(
                L.FoldingRange(
                    start_line=span.start.line,
                    start_character=span.start.character,
                    end_line=span.end.line,
                    end_character=span.end.character,
                )
            )

    def visit_fn(self, e: Fn):
        super().visit_fn(e)
        self._add_folding_range(e.location.range)

    def visit_object(self, e: Object):
        super().visit_object(e)
        self._add_folding_range(e.location.range)

    def visit_obj_comp(self, e: ObjComp):
        super().visit_obj_comp(e)
        self._add_folding_range(e.location.range)

    def visit_array(self, e: Array):
        super().visit_array(e)
        self._add_folding_range(e.location.range)

    def visit_list_comp(self, e: ListComp):
        super().visit_list_comp(e)
        self._add_folding_range(e.location.range)
