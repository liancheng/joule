from itertools import chain

import lsprotocol.types as L

from joule.ast import AnalysisPhase, Document, Id
from joule.maybe import maybe


class DocumentHighlightProvider:
    def __init__(self, tree: Document) -> None:
        assert tree.analysis_phase == AnalysisPhase.ScopeResolved
        self.tree = tree

    def serve(self, pos: L.Position) -> list[L.DocumentHighlight]:
        from lsprotocol.types import DocumentHighlightKind as K

        match self.tree.node_at(pos):
            case Id.Var() as var:
                to_highlight = chain(var.references, [var])
            case Id.VarRef() as ref:
                to_highlight = (
                    id for var in maybe(ref.var) for id in chain(var.references, [var])
                )
            case _:
                to_highlight = ()

        return [
            L.DocumentHighlight(id.location.range, kind)
            for id in to_highlight
            if (kind := K.Write if id.is_a(Id.Var) else K.Read,)
        ]
