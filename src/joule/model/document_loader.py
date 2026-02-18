from pathlib import Path

from joule.ast import URI, Document
from joule.maybe import head_or_none, maybe
from joule.model.scope_resolver import ScopeResolver
from joule.parsing import parse_jsonnet


class DocumentLoader:
    def __init__(self, root_uri: URI) -> None:
        self.trees: dict[URI, Document] = {}
        self.workspace_root = Path.from_uri(root_uri)

    def load_source(self, uri: URI) -> str:
        return Path.from_uri(uri).absolute().read_text()

    def resolve_importee(
        self,
        importer_uri: URI,
        importee: str,
        raise_on_failure: bool = False,
    ) -> Path | None:
        if (path := Path(importee)).is_absolute():
            return path

        match head_or_none(
            joined
            for search_dir in [
                Path.from_uri(importer_uri).parent,
                self.workspace_root.joinpath("vendor"),
                self.workspace_root,
            ]
            if (joined := search_dir.joinpath(importee)).is_file()
        ):
            case None if raise_on_failure:
                raise FileNotFoundError(f"{importee} not found")
            case None:
                return None
            case resolved:
                return resolved

    def load_importee(
        self,
        importer_uri: URI,
        importee: str,
        raise_on_failure: bool = False,
    ) -> Document | None:
        return head_or_none(
            self.load(path.as_uri())
            for path in maybe(
                self.resolve_importee(importer_uri, importee, raise_on_failure)
            )
        )

    def load(self, uri: URI, source: str | None = None) -> Document:
        if source is None:
            source = self.load_source(uri)

        tree = Document.from_cst(uri, parse_jsonnet(source))
        scoped_tree = ScopeResolver().resolve(tree)
        self.trees[uri] = scoped_tree
        return scoped_tree

    def get_or_load(self, uri: URI, source: str | None = None) -> Document:
        return self.trees[uri] if uri in self.trees else self.load(uri, source)
