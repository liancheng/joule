import lsprotocol.types as L

from joule.ast import AnalysisPhase, Document, Id
from joule.util import maybe


class DocumentHighlightProvider:
    def __init__(self, tree: Document) -> None:
        assert tree.analysis_phase == AnalysisPhase.ScopeResolved
        self.tree = tree

    def serve(self, pos: L.Position) -> list[L.DocumentHighlight]:
        match self.tree.node_at(pos):
            case Id.Var() as var:
                return [
                    L.DocumentHighlight(ast.location.range)
                    for ast in var.references + [var]
                ]
            case Id.VarRef() as ref:
                return [
                    L.DocumentHighlight(ast.location.range)
                    for var in maybe(ref.var)
                    for ast in var.references + [var]
                ]
            case _:
                return []
