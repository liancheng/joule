import functools
import itertools
import os
import os.path as P
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Self

import tree_sitter as ts

from joule.maybe import head_or_none, maybe
from joule.syntax import trees as T

__all__ = ["ImportGraph"]


@functools.cache
def import_cursor() -> ts.QueryCursor:
    # Compiling the query once per worker process (it costs ~66 µs each time).
    query = ts.Query(T.language(), "(import) @import")
    return ts.QueryCursor(query)


def collect_importees(path: Path) -> tuple[list[str], bool]:
    try:
        source = path.read_bytes()
    except OSError:
        return [], True

    root_node = T.parser().parse(source).root_node

    def get_import_or_none(node: ts.Node) -> T.Import | None:
        try:
            return T.Import.from_cst(node)
        except T.MalformedError, ValueError:
            return None

    imports = [
        import_.importee.value
        for node in import_cursor().captures(root_node).get("import", [])
        for import_ in maybe(get_import_or_none(node))
        if import_.kind == T.ImportKind.Default
    ]

    return imports, root_node.has_error


class ImportGraph:
    root: Path
    jpaths: list[Path]
    docs: list[Path]

    # Edge fields
    imports: dict[Path, set[Path]]
    imported_by: dict[Path, set[Path]]

    malformed: list[Path]

    # Cache fields
    _is_file: dict[str, bool]
    _same_dir: dict[tuple[str, str], str | None]
    _via_jpaths: dict[str, str | None]

    def __init__(self, root: Path, jpaths: list[Path], docs: list[Path]):
        self.root = root
        self.jpaths = jpaths
        self.docs = docs

        self.imports = defaultdict(set)
        self.imported_by = defaultdict(set)

        self.malformed = []

        self._is_file = {}
        self._same_dir = {}
        self._via_jpaths = {}

    def is_file(self, path: str) -> bool:
        path = P.abspath(path)
        try:
            return self._is_file[path]
        except KeyError:
            result = P.isfile(path)
            self._is_file[path] = result
            return result

    def same_dir(self, importer_dir: str, importee: str) -> str | None:
        importee = P.normpath(importee)

        try:
            return self._same_dir[(importer_dir, importee)]
        except KeyError:
            path = P.join(importer_dir, importee)
            result = path if self.is_file(path) else None
            self._same_dir[(importer_dir, importee)] = result
            return result

    def via_jpaths(self, importee: str) -> str | None:
        importee = P.normpath(importee)

        try:
            return self._via_jpaths[importee]
        except KeyError:
            result = head_or_none(
                path
                for jpath in reversed(self.jpaths)
                if self.is_file(path := P.join(self.root, jpath, importee))
            )
            self._via_jpaths[importee] = result
            return result

    def build(self, batch_size: int = 256) -> Self:
        parallelism = max(2, os.process_cpu_count() or 2)

        with ProcessPoolExecutor(max_workers=parallelism) as executor:
            raw_importees = itertools.zip_longest(
                self.docs,
                executor.map(collect_importees, self.docs, chunksize=batch_size),
            )

        for importer, (importees, error) in raw_importees:
            if error:
                self.malformed.append(importer)
            else:
                for importee in importees:
                    if resolved := self.resolve_importee(importer, importee):
                        self.imports[importer].add(resolved)
                        self.imported_by[resolved].add(importer)

        return self

    def resolve_importee(self, importer: Path, importee: str) -> Path | None:
        # Works on `str` paths with `os.path` to avoid building intermediate `Path`s.
        if P.isabs(importee):
            path = importee if self.is_file(importee) else None
        else:
            importer_dir = P.dirname(P.join(self.root, importer))
            path = self.same_dir(importer_dir, importee) or self.via_jpaths(importee)

        # `is_file` checked the lexically normalized path, so return that one.
        return None if path is None else Path(P.abspath(path))
