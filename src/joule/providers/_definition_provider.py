from collections.abc import Iterable

import lsprotocol.types as L

from joule import trees as T
from joule.maybe import maybe


class DefinitionProvider:
    uri: str
    doc: T.Document

    def __init__(self, uri: str, doc: T.Document):
        self.uri = uri
        self.doc = doc

    def serve(self, pos: L.Position) -> list[L.Location]:
        return [
            location
            for node in maybe(self.doc.node_at(T.Point.from_lsp(pos)))
            for location in self.find_definition(node)
        ]

    def find_definition(self, node: T.Tree) -> Iterable[L.Location]:
        match node:
            case T.Id.VarRef():
                return self.find_var_definition(node)
            case _:
                return ()

    def find_var_definition(self, node: T.Id.VarRef) -> Iterable[L.Location]:
        return (var.span.to_location(self.uri) for var in maybe(node.var))
