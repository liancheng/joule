import dataclasses as D
import logging
import os
from pathlib import Path
from typing import Iterable

from joule import ast as A
from joule.ast import URI
from joule.config import JouleConfig, JouleConfigFactory
from joule.maybe import head_or_none, maybe
from joule.parsing import parse_jsonnet

from .scope_resolver import ScopeResolver

log = logging.getLogger(__name__)


@D.dataclass(frozen=True)
class ImporteeCacheKey:
    importer_uri: URI
    importee_path: str

    @classmethod
    def of(cls, importee: A.Importee):
        return cls(
            importer_uri=importee.location.uri,
            importee_path=importee.value,
        )


class DocumentLoader:
    def __init__(
        self,
        workspace_uri: URI | None,
        config_factory: JouleConfigFactory = lambda: JouleConfig(),
    ) -> None:
        self.trees: dict[URI, A.Document] = {}
        self.workspace_path = Path.from_uri(workspace_uri) if workspace_uri else None
        self.config_factory: JouleConfigFactory = config_factory
        self.importee_paths_cache: dict[ImporteeCacheKey, Path] = {}
        self.importer_cache: dict[URI, Iterable[A.Document]] = {}

    @property
    def config(self) -> JouleConfig:
        return self.config_factory()

    def load_source(self, uri: URI) -> str | None:
        path = Path.from_uri(uri).absolute()
        return path.read_text() if path.is_file() else None

    def resolve_importee(self, importee: A.Importee) -> Path | None:
        key = ImporteeCacheKey.of(importee)
        match self.importee_paths_cache.get(key):
            case None:
                for path in maybe(self._resolve_importee(importee)):
                    self.importee_paths_cache[key] = path
                    return path
            case path:
                return path

        return None

    def _resolve_importee(self, importee: A.Importee) -> Path | None:
        if (path := Path(importee.value)).is_absolute():
            return path

        def search_dirs() -> Iterable[Path]:
            yield Path.from_uri(importee.location.uri).parent
            yield from (
                dir
                for path in maybe(self.workspace_path)
                for dir in self.list_library_search_paths(path)
            )
            yield from maybe(self.workspace_path)

        return head_or_none(
            path.resolve()
            for dir in search_dirs()
            if (path := dir.joinpath(importee.value)).is_file()
        )

    def get_importee(self, importee: A.Importee) -> A.Document | None:
        return head_or_none(
            tree
            for path in maybe(self.resolve_importee(importee))
            for tree in maybe(self.get(path.as_uri()))
        )

    def transitive_importees(self, tree: A.Document) -> Iterable[A.Document]:
        for importee in tree.importees:
            for importee_doc in maybe(self.get_importee(importee)):
                yield importee_doc
                yield from self.transitive_importees(importee_doc)

    def transitive_importers(self, tree: A.Document) -> Iterable[A.Document]:
        match self.importer_cache.get(tree.location.uri):
            case None:
                importers = (
                    candidate
                    for workspace_path in maybe(self.workspace_path)
                    for path in self.list_source_files(workspace_path)
                    for candidate in maybe(self.get(path.as_uri()))
                    if any(
                        importee.location.uri == tree.location.uri
                        for importee in self.transitive_importees(candidate)
                    )
                )
                self.importer_cache[tree.location.uri] = importers
                return importers
            case importers:
                return importers

    def load(self, uri: URI, source: str | None = None) -> A.Document | None:
        if source is None:
            source = self.load_source(uri)

        if source is not None:
            tree = A.AST.from_cst(uri, parse_jsonnet(source))
            if isinstance(tree, A.Document):
                scoped_tree = ScopeResolver().resolve(tree)
                self.trees[uri] = scoped_tree
                return scoped_tree

        return None

    def get(self, uri: URI, source: str | None = None) -> A.Document | None:
        return self.trees.get(uri) if uri in self.trees else self.load(uri, source)

    def list_library_search_paths(self, root: Path) -> Iterable[Path]:
        assert root.is_absolute()

        if any(root.full_match(glob) for glob in self.config.library_paths):
            yield root

        with os.scandir(root) as entries:
            yield from (
                path
                for entry in entries
                if entry.is_dir()
                for path in self.list_library_search_paths(Path(entry.path))
            )

    def list_source_files(self, root: Path) -> Iterable[Path]:
        assert root.is_absolute()

        if any(root.full_match(glob) for glob in self.config.exclude):
            return

        if (
            root.is_file()
            and any(root.full_match(glob) for glob in self.config.include)
            and any(root.name.endswith(suffix) for suffix in self.config.suffixes)
        ):
            yield root

        if root.is_dir():
            with os.scandir(root.as_posix()) as entries:
                yield from (
                    file
                    for entry in entries
                    for file in self.list_source_files(Path(entry.path))
                )
