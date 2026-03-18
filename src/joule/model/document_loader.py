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

    def resolve_importee_path(self, importee: A.Importee) -> Path | None:
        def resolve(importee: A.Importee) -> Path | None:
            if (path := Path(importee.value)).is_absolute():
                return path

            def search_dirs() -> Iterable[Path]:
                yield Path.from_uri(importee.location.uri).parent
                yield from (
                    path
                    for workspace_path in maybe(self.workspace_path)
                    for path in self.extra_library_search_paths(workspace_path)
                )
                yield from maybe(self.workspace_path)

            return head_or_none(
                path.resolve()
                for dir in search_dirs()
                if (path := dir.joinpath(importee.value)).is_file()
            )

        key = ImporteeCacheKey.of(importee)

        return self.importee_paths_cache.get(key) or head_or_none(
            self.importee_paths_cache.setdefault(key, path)
            for path in maybe(resolve(importee))
        )

    def from_importee(self, importee: A.Importee) -> A.Document | None:
        return head_or_none(
            tree
            for path in maybe(self.resolve_importee_path(importee))
            for tree in maybe(self.from_uri(path.as_uri()))
        )

    def transitive_importees(self, tree: A.Document) -> Iterable[A.Document]:
        for importee in tree.importees:
            for importee_doc in maybe(self.from_importee(importee)):
                yield importee_doc
                yield from self.transitive_importees(importee_doc)

    def transitive_importers(self, tree: A.Document) -> Iterable[A.Document]:
        return self.importer_cache.get(tree.location.uri) or (
            self.importer_cache.setdefault(
                tree.location.uri,
                (
                    candidate
                    for workspace_path in maybe(self.workspace_path)
                    for path in self.source_files(workspace_path)
                    for candidate in maybe(self.from_uri(path.as_uri()))
                    if any(
                        importee.location.uri == tree.location.uri
                        for importee in self.transitive_importees(candidate)
                    )
                ),
            )
        )

    def load_from_uri(self, uri: URI) -> A.Document | None:
        return head_or_none(
            self.load_from_source(uri, path.read_text())
            for path in maybe(Path.from_uri(uri).absolute())
            if path.is_file()
        )

    def load_and_cache_from_uri(self, uri: URI) -> A.Document | None:
        return head_or_none(
            self.trees.setdefault(uri, doc) for doc in maybe(self.load_from_uri(uri))
        )

    def load_from_source(self, uri: URI, source: str) -> A.Document:
        cst = parse_jsonnet(source)
        doc = A.Document.from_cst(uri, cst)
        return ScopeResolver().resolve(doc)

    def load_and_cache_from_source(self, uri: URI, source: str) -> A.Document:
        return self.trees.setdefault(uri, self.load_from_source(uri, source))

    def from_uri(self, uri: URI) -> A.Document | None:
        return self.trees.get(uri) or self.load_and_cache_from_uri(uri)

    def from_source(self, uri: URI, source: str) -> A.Document:
        return self.trees.get(uri) or self.load_and_cache_from_source(uri, source)

    def extra_library_search_paths(self, root: Path) -> Iterable[Path]:
        assert root.is_absolute()

        if any(root.full_match(glob) for glob in self.config.library_paths):
            yield root

        with os.scandir(root) as entries:
            yield from (
                path
                for entry in entries
                if entry.is_dir()
                for path in self.extra_library_search_paths(Path(entry.path))
            )

    def source_files(self, root: Path) -> Iterable[Path]:
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
                    for file in self.source_files(Path(entry.path))
                )
