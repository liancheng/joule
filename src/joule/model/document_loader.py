import logging
from itertools import chain
from pathlib import Path
from typing import Iterable

from joule.ast import AST, URI, Document, Importee
from joule.maybe import head_or_none, maybe
from joule.parsing import parse_jsonnet

from .scope_resolver import ScopeResolver

log = logging.getLogger(__name__)


class DocumentLoader:
    def __init__(self, workspace_uri: URI | None) -> None:
        self.trees: dict[URI, Document] = {}
        self.workspace_path = Path.from_uri(workspace_uri) if workspace_uri else None
        self.exclude_globs: list[str] = []
        self.include_globs: list[str] = []

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
                for dir in self.list_paths(path, self.include_globs, self.exclude_globs)
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

    def list_paths(
        self,
        root: Path,
        include_globs: list[str],
        exclude_globs: list[str],
        source_globs: list[str] | None = None,
    ) -> Iterable[Path]:
        assert root.is_absolute()

        for dir_path, dir_names, file_names in root.walk():
            dir_names[:] = [
                dir
                for dir in dir_names
                for glob in exclude_globs
                if not Path(dir).full_match(glob)
            ]

            if not source_globs:
                yield from (
                    dir_path.joinpath(dir)
                    for dir in dir_names
                    for glob in include_globs
                    if Path(dir).full_match(glob)
                )
            else:
                yield from (
                    dir_path.joinpath(file)
                    for file in file_names
                    for glob in source_globs
                    if Path(file).match(glob)
                )

    def list_folders(self, root: Path) -> Iterable[Path]:
        return self.list_paths(root, self.include_globs, self.exclude_globs)

    def list_source_files(self, root: Path) -> Iterable[Path]:
        return self.list_paths(
            root,
            include_globs=self.include_globs,
            exclude_globs=self.exclude_globs,
            source_globs=[
                "*.jsonnet",
                "*.libsonnet",
                "*.jsonnet.TEMPLATE",
            ],
        )
