import logging
import os
from functools import cached_property
from pathlib import Path
from typing import Callable, Iterable

import joule.ast as A
from joule.ast import URI
from joule.config import JouleConfig
from joule.maybe import head_or_none, maybe
from joule.model.scope_resolver import ScopeResolver
from joule.parsing import parse_jsonnet

log = logging.getLogger(__name__)


class DocumentStore:
    config: JouleConfig
    workspace_uri: URI
    library_paths: list[Path]
    trees: dict[URI, A.Document]
    imports: dict[URI, set[URI]]
    imported_by: dict[URI, set[URI]]

    def __init__(self, config: JouleConfig, workspace_uri: URI) -> None:
        self.config = config
        self.workspace_uri = workspace_uri
        self.library_paths = []
        self.trees = {}
        self.imports = {}
        self.imported_by = {}

    @cached_property
    def workspace_path(self) -> Path:
        return Path.from_uri(self.workspace_uri)

    def scan(self) -> Iterable[Path]:
        """Scans the workspace for source files and library search paths."""

        def walk(root: Path) -> Iterable[Path]:
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
                if any(root.full_match(glob) for glob in self.config.library_paths):
                    yield root

                with os.scandir(root.as_posix()) as entries:
                    yield from (
                        file for entry in entries for file in walk(Path(entry.path))
                    )

        yield from walk(self.workspace_path)

    def load_workspace(
        self,
        paths: Iterable[Path] | None = None,
        callback: Callable[[Path], None] | None = None,
    ):
        """Loads and indexes all source files in the workspace."""

        if paths is None:
            paths = self.scan()

        for path in paths:
            if callback is not None:
                callback(path)

            if path.is_dir():
                if any(path.full_match(glob) for glob in self.config.library_paths):
                    self.library_paths.append(path)
            elif path.is_file():
                uri = path.as_uri()
                try:
                    self.load_uri(uri)
                except Exception:
                    log.exception("Failed to load source file: %s", uri)

        for ast in self.trees.values():
            self.index_importees(ast)

    def index_importees(self, ast: A.Document):
        for importee in ast.importees:
            for uri in maybe(self.resolve_importee(importee)):
                self.imports.setdefault(ast.location.uri, set()).add(uri)
                self.imported_by.setdefault(uri, set()).add(ast.location.uri)

    def load_uri(self, uri: URI) -> A.Document:
        cst = parse_jsonnet(Path.from_uri(uri).read_text())
        ast = A.Document.from_cst(uri, cst)
        resolved = ScopeResolver().resolve(ast)
        self.trees[uri] = resolved
        return resolved

    def resolve_importee(self, importee: A.Importee) -> URI | None:
        if (path := Path(importee.value)).is_absolute():
            return path.as_uri()

        def search_dirs() -> Iterable[Path]:
            yield Path.from_uri(importee.location.uri).parent
            yield from self.library_paths
            yield self.workspace_path

        return head_or_none(
            path.resolve().as_uri()
            for dir in search_dirs()
            if (path := dir.joinpath(importee.value)).is_file()
        )

    def recursive_importers(self, uri: URI) -> Iterable[URI]:
        def recurse(uri: URI, visited: set[URI]) -> Iterable[URI]:
            if uri in visited:
                return

            visited.add(uri)

            for importer in self.imported_by.get(uri, set()):
                yield importer
                for recursive_importer in self.recursive_importers(importer):
                    if recursive_importer not in visited:
                        visited.add(recursive_importer)
                        yield recursive_importer

        yield from recurse(uri, set())
