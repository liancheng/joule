import lsprotocol.types as L

from joule.ast import Bind, Document, Id
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
