from itertools import chain
from pathlib import Path
from typing import Iterable

from joule.ast import AST, URI, Document, Importee
from joule.maybe import maybe
from joule.parsing import parse_jsonnet

from .scope_resolver import ScopeResolver


class DocumentLoader:
    def __init__(self, workspace_uri: URI | None) -> None:
        self.trees: dict[URI, Document] = {}
        self.workspace_path = Path.from_uri(workspace_uri) if workspace_uri else None

    def load_source(self, uri: URI) -> str | None:
        path = Path.from_uri(uri).absolute()
        return path.read_text() if path.is_file() else None

    def resolve_importee(self, importee: Importee) -> Path | None:
        if (path := Path(importee.value)).is_absolute():
            return path

        importer_uri = importee.location.uri

        # TODO: Make search directories customizable
        search_dirs = chain(
            [Path.from_uri(importer_uri).parent],
            (
                dir
                for path in maybe(self.workspace_path)
                for dir in path.rglob("vendor/")
            ),
            maybe(self.workspace_path),
        )

        for dir in search_dirs:
            if (joined := dir.joinpath(importee.value)).is_file():
                return joined

        return None

    def get_importee(self, importee: Importee) -> Document | None:
        if path := self.resolve_importee(importee):
            return self.get(path.as_uri())
        else:
            return None

    def load(self, uri: URI, source: str | None = None) -> Document | None:
        if source is None:
            source = self.load_source(uri)

        if source is not None:
            tree = AST.from_cst(uri, parse_jsonnet(source))
            if isinstance(tree, Document):
                scoped_tree = ScopeResolver().resolve(tree)
                self.trees[uri] = scoped_tree
                return scoped_tree

        return None

    def get(self, uri: URI, source: str | None = None) -> Document | None:
        return self.trees.get(uri) if uri in self.trees else self.load(uri, source)

    def walk(self, root: Path) -> Iterable[Path]:
        root = root.resolve()

        def is_jsonnet_file(name: str) -> bool:
            return (
                name.endswith(".jsonnet")
                or name.endswith(".libsonnet")
                or name.endswith(".jsonnet.TEMPLATE")
            )

        for dir_path, dir_names, file_names in root.walk():
            if ".git" in dir_names:
                dir_names.remove(".git")

            yield from (dir_path.joinpath(f) for f in file_names if is_jsonnet_file(f))

    def load_all(self, root: Path) -> Iterable[Document]:
        return (
            doc for path in self.walk(root) for doc in maybe(self.load(path.as_uri()))
        )
