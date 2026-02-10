from typing import Callable

import lsprotocol.types as L

from joule.ast import Bind, Document, ForSpec, Id, Param
from joule.visitor import Visitor


class InlayHintProvider(Visitor):
    def __init__(self, tree: Document) -> None:
        self.tree = tree
        self.hints: list[L.InlayHint] = []

    def serve(self):
        self.visit(self.tree)
        return self.hints

    def visit_var_ref(self, e: Id.VarRef):
        self.hints.append(L.InlayHint(e.location.range.end, ""))

    def visit_bind(self, b: Bind):
        self.hints.append(
            L.InlayHint(
                b.id.location.range.end,
                [
                    L.InlayHintLabelPart(""),
                    L.InlayHintLabelPart(str(len(b.id.references))),
                ],
            )
        )

    def visit_param(self, p: Param):
        self.hints.append(
            L.InlayHint(
                p.id.location.range.end,
                [
                    L.InlayHintLabelPart(""),
                    L.InlayHintLabelPart(str(len(p.id.references))),
                ],
            )
        )

    def visit_for_spec(self, s: ForSpec, next: Callable[[], None]):
        self.hints.append(
            L.InlayHint(
                s.id.location.range.end,
                [
                    L.InlayHintLabelPart(""),
                    L.InlayHintLabelPart(str(len(s.id.references))),
                ],
            )
        )
        next()
