import lsprotocol.types as L

from joule.ast import URI
from joule.document_model import DocumentIndex, LocationKey
from joule.util import maybe

LocationMap = dict[LocationKey, list[L.Location]]


class WorkspaceIndex:
    def __init__(self, root_uri: URI):
        self.root_uri = root_uri
        self.docs: dict[URI, DocumentIndex] = {}

    def definitions(self, uri: URI, position: L.Position) -> list[L.Location]:
        local_defs = [
            location
            for doc in maybe(self.docs.get(uri))
            for node in maybe(doc.doc.node_at(position))
            for location in doc.local_definition(node.location)
        ]

        return local_defs

    def references(self, uri: URI, position: L.Position) -> list[L.Location]:
        return [
            location
            for doc in maybe(self.docs.get(uri))
            for node in maybe(doc.doc.node_at(position))
            for location in doc.local_references(node.location)
        ]

    def load(self, uri: URI, source: str | None):
        self.docs[uri] = DocumentIndex.load(self.root_uri, uri, source)

    def get_or_load(self, uri: URI, source: str | None = None) -> DocumentIndex:
        if uri not in self.docs:
            self.load(uri, source)
        return self.docs[uri]
