import os
from functools import cached_property
from pathlib import Path
from typing import Iterable

import joule.ast as A
from joule.ast import URI
from joule.config import JouleConfig
from joule.model.scope_resolver import ScopeResolver
from joule.parsing import parse_jsonnet


class DocumentStore:
    config: JouleConfig
    workspace_uri: URI
    trees: dict[URI, A.AST] = {}
    library_paths: list[Path] = []
    importees: dict[A.ImporteeKey, Path] = {}
    imports: dict[URI, list[URI]] = {}
    importedBy: dict[URI, list[URI]] = {}

    def __init__(self, config: JouleConfig, workspace_uri: URI) -> None:
        self.config = config
        self.workspace_uri = workspace_uri

    @cached_property
    def workspace_path(self) -> Path:
        return Path.from_uri(self.workspace_uri)

    def load_workspace(self):
        def enumerate(root: Path) -> Iterable[Path]:
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
                        for file in enumerate(Path(entry.path))
                    )

        self.trees = {
            uri: ScopeResolver().resolve(ast)
            for path in enumerate(self.workspace_path)
            if (uri := path.as_uri())
            if (source := path.read_text())
            if (ast := A.Document.from_cst(uri, parse_jsonnet(source)))
        }

    def enumerate_library_paths(self, root: Path) -> Iterable[Path]:
        assert root.is_absolute()

        if any(root.full_match(glob) for glob in self.config.library_paths):
            yield root

        with os.scandir(root) as entries:
            yield from (
                path
                for entry in entries
                if entry.is_dir()
                for path in self.enumerate_library_paths(Path(entry.path))
            )
