from collections.abc import Iterable

import lsprotocol.types as L

from joule.maybe import maybe
from joule.syntax import trees as T


class ReferencesProvider:
    uri: str
    doc: T.Document

    def __init__(self, uri: str, doc: T.Document):
        self.uri = uri
        self.doc = doc

    def serve(self, pos: L.Position) -> list[L.Location]:
        return [
            location
            for node in maybe(self.doc.node_at(T.Point.from_lsp(pos)))
            for location in self.find_references(node)
        ]

    def find_references(self, node: T.Tree) -> Iterable[L.Location]:
        match node:
            case T.Id.Var():
                return self.find_var_references(node)
            case _:
                return ()

    def find_var_references(self, node: T.Id.Var) -> Iterable[L.Location]:
        return (
            ref.span.to_location(self.uri)
            for refs in maybe(node.references)
            for ref in refs
        )
