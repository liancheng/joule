from itertools import chain

import lsprotocol.types as L

from joule import ast as A
from joule.ast import AnalysisPhase
from joule.maybe import maybe


class DocumentHighlightProvider:
    def serve(self, tree: A.Document, pos: L.Position) -> list[L.DocumentHighlight]:
        assert tree.analysis_phase == AnalysisPhase.ScopeResolved
        from lsprotocol.types import DocumentHighlightKind as K

        match node := tree.node_at(pos):
            case A.Field():
                match value := node.value:
                    case A.Fn():
                        to_highlight = value.body.tails
                    case _:
                        to_highlight = value.tails
            case A.Fn():
                to_highlight = node.body.tails
            case A.Id.Var():
                to_highlight = chain(node.references, [node])
            case A.Id.VarRef():
                to_highlight = (
                    id for var in maybe(node.var) for id in chain(var.references, [var])
                )
            case A.If() | A.Local():
                to_highlight = node.tails
            case _:
                to_highlight = ()

        return [
            L.DocumentHighlight(id.location.range, kind)
            for id in to_highlight
            if (kind := K.Write if isinstance(id, A.Id.Var) else K.Read,)
        ]
