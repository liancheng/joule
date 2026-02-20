from itertools import chain
from pathlib import Path
from typing import Iterable

from joule.ast import AST, URI, Document, Importee
from joule.maybe import maybe
from joule.parsing import parse_jsonnet

from .scope_resolver import ScopeResolver


class DocumentLoader:
    def __init__(self, root_uri: URI) -> None:
        self.trees: dict[URI, Document] = {}
        self.workspace_root = Path.from_uri(root_uri)

    def load_source(self, uri: URI) -> str | None:
        path = Path.from_uri(uri).absolute()
        return path.read_text() if path.is_file() else None

    def resolve_importee_path(self, importer_uri: URI, importee: str) -> Path | None:
        if (path := Path(importee)).is_absolute():
            return path

        # TODO: Make search directories customizable
        search_dirs = chain(
            [Path.from_uri(importer_uri).parent],
            self.workspace_root.rglob("vendor/"),
            self.workspace_root.rglob("jsonnet/"),
            [self.workspace_root],
        )

        for dir in search_dirs:
            if (joined := dir.joinpath(importee)).is_file():
                return joined

        return None

    def get_importee(self, importee: Importee) -> Document | None:
        if path := self.resolve_importee_path(importee.location.uri, importee.value):
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

    def load_all_sources(self, root: Path | None = None) -> Iterable[tuple[URI, str]]:
        if root is None:
            root = self.workspace_root
        root = root.absolute()

        def is_jsonnet_file(name: str) -> bool:
            return (
                name.endswith(".jsonnet")
                or name.endswith(".libsonnet")
                or name.endswith(".jsonnet.TEMPLATE")
            )

        for dir_path, dir_names, file_names in root.walk():
            if ".git" in dir_names:
                dir_names.remove(".git")

            yield from (
                (path.as_uri(), path.read_text())
                for f in file_names
                if is_jsonnet_file(f)
                if (path := dir_path.joinpath(f))
            )

    def load_all(self, root: Path | None = None) -> Iterable[Document]:
        return (
            doc
            for uri, source in self.load_all_sources(root)
            for doc in maybe(self.load(uri, source))
        )
