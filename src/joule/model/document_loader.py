import logging
import os
from itertools import chain
from pathlib import Path
from typing import Iterable

from joule import ast as A
from joule.ast import URI
from joule.config import JouleConfig, JouleConfigFactory
from joule.maybe import head_or_none, maybe
from joule.parsing import parse_jsonnet

from .scope_resolver import ScopeResolver

log = logging.getLogger(__name__)


class DocumentLoader:
    def __init__(
        self,
        workspace_uri: URI | None,
        config_factory: JouleConfigFactory = lambda: JouleConfig(),
    ) -> None:
        self.trees: dict[URI, A.Document] = {}
        self.workspace_path = Path.from_uri(workspace_uri) if workspace_uri else None
        self.config_factory: JouleConfigFactory = config_factory

    @property
    def config(self) -> JouleConfig:
        return self.config_factory()

    def load_source(self, uri: URI) -> str | None:
        path = Path.from_uri(uri).absolute()
        return path.read_text() if path.is_file() else None

    def resolve_importee(self, importee: A.Importee) -> Path | None:
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
            path.resolve()
            for dir in search_dirs
            if (path := dir.joinpath(importee.value)).is_file()
        )

    def get_importee(self, importee: A.Importee) -> A.Document | None:
        if path := self.resolve_importee(importee):
            return self.get(path.as_uri())
        else:
            return None

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
