import logging
import os
from itertools import chain
from pathlib import Path
from typing import Iterable

from joule.ast import AST, URI, Document, Importee
from joule.config import JouleConfig
from joule.maybe import head_or_none, maybe
from joule.parsing import parse_jsonnet

from .scope_resolver import ScopeResolver

log = logging.getLogger(__name__)


class DocumentLoader:
    def __init__(
        self,
        workspace_uri: URI | None,
        config: JouleConfig,
    ) -> None:
        self.trees: dict[URI, Document] = {}
        self.workspace_path = Path.from_uri(workspace_uri) if workspace_uri else None
        self.config: JouleConfig = config

    def load_source(self, uri: URI) -> str | None:
        path = Path.from_uri(uri).absolute()
        return path.read_text() if path.is_file() else None

    def resolve_importee(self, importee: Importee) -> Path | None:
        if (path := Path(importee.value)).is_absolute():
            return path

        search_dirs = chain(
            [Path.from_uri(importee.location.uri).parent],
            (
                dir
                for path in maybe(self.workspace_path)
                for dir in self.list_library_search_paths(path)
            ),
            maybe(self.workspace_path),
        )

        return head_or_none(
            path
            for dir in search_dirs
            if (path := dir.joinpath(importee.value)).is_file()
        )

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

    def list_library_search_paths(self, root: Path) -> Iterable[Path]:
        assert root.is_absolute()

        with os.scandir(root.as_posix()) as entries:
            yield from (
                path
                for config in maybe(self.config)
                for entry in entries
                if entry.is_dir() and (dir := Path(entry.path))
                if any(dir.full_match(glob) for glob in config.library_search_paths)
                for path in chain([dir], self.list_library_search_paths(dir))
            )

    def list_source_files(self, root: Path) -> Iterable[Path]:
        assert root.is_absolute()

        with os.scandir(root.as_posix()) as entries:
            for entry in entries:
                if entry.is_dir():
                    yield from (
                        file
                        for config in maybe(self.config)
                        if (dir := Path(entry.path))
                        if not any(dir.full_match(g) for g in config.exclude_folders)
                        for file in self.list_source_files(dir)
                    )
                elif entry.is_file():
                    file = Path(entry.path)
                    yield from (
                        file
                        for config in maybe(self.config)
                        if any(file.full_match(g) for g in config.include_folders)
                        if any(file.match(g) for g in config.include_files)
                    )
