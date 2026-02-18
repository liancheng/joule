from enum import StrEnum
from typing import Callable

import lsprotocol.types as L

from joule.ast import AnalysisPhase, Bind, Document, ForSpec, Id, Param
from joule.maybe import maybe
from joule.visitor import Visitor


class Icon(StrEnum):
    UpArrow = ""
    DownArrow = ""


class InlayHintProvider(Visitor):
    def __init__(self) -> None:
        self.hints: list[L.InlayHint] = []

    def serve(self, tree: Document):
        assert tree.analysis_phase == AnalysisPhase.ScopeResolved
        self.visit(tree)
        return self.hints

    def visit_var_ref(self, e: Id.VarRef):
        super().visit_var_ref(e)

        for_spec_var_ref = next(
            (
                binding.target.is_a(ForSpec)
                for var in maybe(e.var)
                for binding in maybe(var.binding)
            ),
            False,
        )

        if e.var is not None:
            self._add_hint(
                e.location.range.end,
                # Marks for-spec variable references with an down-arrow as for-spec
                # variables are defined after their references.
                Icon.DownArrow if for_spec_var_ref else Icon.UpArrow,
            )

    def visit_bind(self, b: Bind):
        super().visit_bind(b)
        n_refs = len(b.id.references)
        self._add_hint(b.id.location.range.end, [Icon.DownArrow, str(n_refs)])

    def visit_param(self, p: Param):
        super().visit_param(p)
        n_refs = len(p.id.references)
        self._add_hint(p.id.location.range.end, [Icon.DownArrow, str(n_refs)])

    def visit_for_spec(self, s: ForSpec, next: Callable[[], None]):
        def new_next():
            n_refs = len(s.id.references)
            # Marks for-spec variables with an up-arrow as for-spec variables
            # are defined after their references.
            self._add_hint(s.id.location.range.end, [Icon.UpArrow, str(n_refs)])
            next()

        super().visit_for_spec(s, new_next)

    def _add_hint(self, pos: L.Position, label_parts: str | list[str]):
        label = (
            [L.InlayHintLabelPart(part) for part in label_parts]
            if isinstance(label_parts, list)
            else label_parts
        )
        self.hints.append(L.InlayHint(pos, label))
