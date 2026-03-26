import os
from functools import cached_property
from itertools import filterfalse, tee
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

    def _enumerate(
        self,
        root: Path,
        callback: Callable[[Path], None] | None = None,
    ) -> Iterable[Path]:
        assert root.is_absolute()

        if any(root.full_match(glob) for glob in self.config.exclude):
            return

        if (
            root.is_file()
            and any(root.full_match(glob) for glob in self.config.include)
            and any(root.name.endswith(suffix) for suffix in self.config.suffixes)
        ):
            if callback is not None:
                callback(root)
            yield root

        if root.is_dir():
            if callback is not None:
                callback(root)
            yield root

            with os.scandir(root.as_posix()) as entries:
                yield from (
                    file
                    for entry in entries
                    for file in self._enumerate(Path(entry.path), callback)
                )

    def load_workspace(
        self,
        callback: Callable[[Path], None] | None = None,
    ):
        def partition(pred, iterable):
            i1, i2 = tee(iterable)
            return filter(pred, i1), filterfalse(pred, i2)

        dirs, files = partition(
            lambda path: path.is_dir(),
            self._enumerate(self.workspace_path, callback),
        )

        self.trees = {
            uri: ScopeResolver().resolve(ast)
            for file in files
            if file.is_file()
            if (uri := file.as_uri())
            if (source := file.read_text())
            if (ast := A.Document.from_cst(uri, parse_jsonnet(source)))
        }

        self.library_paths = [
            dir
            for dir in dirs
            if any(dir.full_match(glob) for glob in self.config.library_paths)
        ]
