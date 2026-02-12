from typing import Iterable

import lsprotocol.types as L

from joule.ast import AST, AnalysisPhase, Document, Id
from joule.maybe import maybe


class ReferencesProvider:
    def __init__(self, tree: Document) -> None:
        assert tree.analysis_phase == AnalysisPhase.ScopeResolved
        self.tree = tree

    def serve(self, pos: L.Position) -> list[L.Location]:
        return [
            location
            for node in maybe(self.tree.node_at(pos))
            for location in self.find_references(node)
        ]

    def find_references(self, node: AST) -> Iterable[L.Location]:
        match node:
            case Id.Var():
                return (ref.location for ref in node.references)
            case _:
                return ()
