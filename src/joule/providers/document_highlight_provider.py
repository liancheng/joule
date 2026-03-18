from typing import Iterable

import lsprotocol.types as L

from joule import ast as A
from joule.ast import AnalysisPhase


class DocumentHighlightProvider:
    def serve(self, tree: A.Document, pos: L.Position) -> list[L.DocumentHighlight]:
        assert tree.analysis_phase == AnalysisPhase.ScopeResolved
        from lsprotocol.types import DocumentHighlightKind as K

        def to_highlight() -> Iterable[A.AST]:
            match node := tree.node_at(pos):
                case A.Field() if isinstance(node.value, A.Fn):
                    yield from node.value.body.tails

                case A.Field():
                    yield from node.value.tails

                case A.Fn():
                    yield from node.body.tails

                case A.Id.Var():
                    yield from node.references
                    yield node

                case A.Id.VarRef() if node.var is not None:
                    yield node.var
                    yield from node.var.references

                case A.If() | A.Local():
                    yield from node.tails

                case _:
                    pass

        return [
            L.DocumentHighlight(id.location.range, kind)
            for id in to_highlight()
            if (kind := K.Write if isinstance(id, A.Id.Var) else K.Read,)
        ]
