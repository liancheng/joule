import lsprotocol.types as L

from joule.ast import AST, Document, Id
from joule.util import maybe


class ReferencesProvider:
    def __init__(self, tree: Document) -> None:
        self.tree = tree

    def serve(self, pos: L.Position) -> list[L.Location]:
        return [
            location
            for node in maybe(self.tree.node_at(pos))
            for location in self.find_references(node)
        ]

    def find_references(self, node: AST) -> list[L.Location]:
        match node:
            case Id.Var():
                return [ref.location for ref in node.references]
            case Id.Field():
                return []
            case _:
                return []
