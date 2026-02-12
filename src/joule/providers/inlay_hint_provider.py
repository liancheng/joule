from typing import Callable

import lsprotocol.types as L

from joule.ast import AnalysisPhase, Bind, Document, ForSpec, Id, Param
from joule.visitor import Visitor


class InlayHintProvider(Visitor):
    def __init__(self, tree: Document) -> None:
        assert tree.analysis_phase == AnalysisPhase.ScopeResolved
        self.tree = tree
        self.hints: list[L.InlayHint] = []

    def serve(self):
        self.visit(self.tree)
        return self.hints

    def visit_var_ref(self, e: Id.VarRef):
        super().visit_var_ref(e)
        self._add_hint(e.location.range.end, "")

    def visit_bind(self, b: Bind):
        super().visit_bind(b)
        self._add_hint(
            b.id.location.range.end,
            ["", str(len(b.id.references))],
        )

    def visit_param(self, p: Param):
        super().visit_param(p)
        self._add_hint(
            p.id.location.range.end,
            ["", str(len(p.id.references))],
        )

    def visit_for_spec(self, s: ForSpec, next: Callable[[], None]):
        def new_next():
            self._add_hint(
                s.id.location.range.end,
                ["", str(len(s.id.references))],
            )
            next()

        super().visit_for_spec(s, new_next)

    def _add_hint(self, pos: L.Position, label_parts: str | list[str]):
        label = (
            [L.InlayHintLabelPart(part) for part in label_parts]
            if isinstance(label_parts, list)
            else label_parts
        )
        self.hints.append(L.InlayHint(pos, label))
