from pathlib import Path

from joule.ast import URI, Document
from joule.model.scope_resolver import ScopeResolver
from joule.parsing import parse_jsonnet


class DocumentLoader:
    def __init__(self, workspace_root: URI) -> None:
        self.trees: dict[URI, Document] = {}
        self.workspace_root = workspace_root

    def load_source(self, uri: URI) -> str:
        return Path.from_uri(uri).absolute().read_text()

    def load(self, uri: URI, source: str | None) -> Document:
        if source is None:
            source = self.load_source(uri)
        tree = Document.from_cst(uri, parse_jsonnet(source))
        scoped_tree = ScopeResolver().resolve(tree)
        self.trees[uri] = scoped_tree
        return scoped_tree

    def get_or_load(self, uri: URI, source: str | None = None) -> Document:
        return self.trees[uri] if uri in self.trees else self.load(uri, source)
