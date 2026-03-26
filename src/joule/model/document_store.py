import os
from functools import cached_property
from pathlib import Path
from typing import Callable, Iterable

import joule.ast as A
from joule.ast import URI
from joule.config import JouleConfig
from joule.model.scope_resolver import ScopeResolver
from joule.parsing import parse_jsonnet


class DocumentStore:
    config: JouleConfig = JouleConfig()
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

    def enumerate(
        self,
        root: Path,
    ) -> Iterable[Path]:
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
            yield root

            with os.scandir(root.as_posix()) as entries:
                yield from (
                    file
                    for entry in entries
                    for file in self.enumerate(Path(entry.path))
                )

    def load_workspace(
        self,
        paths: Iterable[Path],
        callback: Callable[[Path], None] | None = None,
    ):
        for path in paths:
            if callback is not None:
                callback(path)

            if path.is_dir():
                if any(path.full_match(glob) for glob in self.config.library_paths):
                    self.library_paths.append(path)
            elif path.is_file():
                uri = path.as_uri()
                try:
                    cst = parse_jsonnet(path.read_text())
                    ast = A.Document.from_cst(uri, cst)
                    self.trees[uri] = ScopeResolver().resolve(ast)
                finally:
                    pass
