from pathlib import Path

from joule.ast import URI, Document
from joule.model.scope_resolver import ScopeResolver
from joule.parsing import parse_jsonnet


class DocumentLoader:
    def __init__(self, root_uri: URI) -> None:
        self.trees: dict[URI, Document] = {}
        self.workspace_root = Path.from_uri(root_uri)

    def load_source(self, uri: URI) -> str | None:
        path = Path.from_uri(uri).absolute()
        return path.read_text() if path.is_file() else None

    def resolve_importee(
        self,
        importer_uri: URI,
        importee: str,
    ) -> Path | None:
        if (path := Path(importee)).is_absolute():
            return path

        for search_dir in [
            Path.from_uri(importer_uri).parent,
            self.workspace_root.joinpath("vendor"),
            self.workspace_root,
        ]:
            if (joined := search_dir.joinpath(importee)).is_file():
                return joined

        return None

    def load_importee(
        self,
        importer_uri: URI,
        importee: str,
    ) -> Document | None:
        if path := self.resolve_importee(importer_uri, importee):
            return self.load(path.as_uri())
        else:
            return None

    def load(
        self,
        uri: URI,
        source: str | None = None,
    ) -> Document | None:
        if source is None:
            source = self.load_source(uri)

        if source is not None:
            tree = Document.from_cst(uri, parse_jsonnet(source))
            scoped_tree = ScopeResolver().resolve(tree)
            self.trees[uri] = scoped_tree
            return scoped_tree
        else:
            return None

    def get_or_load(
        self,
        uri: URI,
        source: str | None = None,
    ) -> Document | None:
        return self.trees.get(uri) if uri in self.trees else self.load(uri, source)
