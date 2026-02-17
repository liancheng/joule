from typing import Iterable

import lsprotocol.types as L

from joule.ast import AST, AnalysisPhase, Document, Id
from joule.maybe import maybe


class ReferencesProvider:
    def serve(self, tree: Document, pos: L.Position) -> list[L.Location]:
        assert tree.analysis_phase == AnalysisPhase.ScopeResolved
        return [
            location
            for node in maybe(tree.node_at(pos))
            for location in self.find_references(node)
        ]

    def find_references(self, node: AST) -> Iterable[L.Location]:
        return (
            (ref.location for ref in node.references)
            if isinstance(node, Id.Var)
            else ()
        )
