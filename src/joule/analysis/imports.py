import functools
import itertools
import os
import os.path as P
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import override

import tree_sitter as ts

from joule.maybe import head_or_none, maybe
from joule.syntax import trees as T

__all__ = [
    "CachedImportResolver",
    "ImportGraph",
    "ImportGraphBuilder",
    "ImportResolver",
]


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


class ImportResolver:
    """Resolves importees like Jsonnet's file importer, without caching.

    An absolute importee is used as-is. Otherwise it is tried relative to the importer's
    directory first, then relative to each jpath, later jpaths first. The first candidate
    naming an existing file wins. Relative importers and jpaths are taken relative to
    the workspace root.

    Paths are normalized lexically: `.` and `..` are collapsed as text, and symlinks are
    not followed.
    """

    root: Path
    jpaths: list[Path]

    def __init__(self, root: Path, jpaths: list[Path]):
        self.root = root
        self.jpaths = jpaths

    def is_file(self, path: str) -> bool:
        return P.isfile(P.abspath(path))

    def same_dir(self, importer_dir: str, importee: str) -> str | None:
        path = P.join(importer_dir, importee)
        return path if self.is_file(path) else None

    def via_jpaths(self, importee: str) -> str | None:
        return head_or_none(
            path
            for jpath in reversed(self.jpaths)
            if self.is_file(path := P.join(self.root, jpath, importee))
        )

    def resolve(self, importer: Path, importee: str) -> Path | None:
        # Works on `str` paths with `os.path` to avoid building intermediate `Path`s.
        if P.isabs(importee):
            path = importee if self.is_file(importee) else None
        else:
            importer_dir = P.dirname(P.join(self.root, importer))
            path = self.same_dir(importer_dir, importee) or self.via_jpaths(importee)

        # `is_file` checked the lexically normalized path, so return that one.
        return None if path is None else Path(P.abspath(path))


class CachedImportResolver(ImportResolver):
    """An `ImportResolver` that caches lookups, for resolving many importees in bulk.

    The caches record only whether files exist, so they stay valid until a file is
    created or deleted, or the jpaths change.
    """

    _is_file: dict[str, bool]
    _same_dir: dict[tuple[str, str], str | None]
    _via_jpaths: dict[str, str | None]

    def __init__(self, root: Path, jpaths: list[Path]):
        super().__init__(root, jpaths)
        self._is_file = {}
        self._same_dir = {}
        self._via_jpaths = {}

    @override
    def is_file(self, path: str) -> bool:
        path = P.abspath(path)
        try:
            return self._is_file[path]
        except KeyError:
            result = P.isfile(path)
            self._is_file[path] = result
            return result

    @override
    def same_dir(self, importer_dir: str, importee: str) -> str | None:
        # Normalized so that different spellings of one importee share an entry.
        importee = P.normpath(importee)
        try:
            return self._same_dir[(importer_dir, importee)]
        except KeyError:
            result = super().same_dir(importer_dir, importee)
            self._same_dir[(importer_dir, importee)] = result
            return result

    @override
    def via_jpaths(self, importee: str) -> str | None:
        importee = P.normpath(importee)
        try:
            return self._via_jpaths[importee]
        except KeyError:
            result = super().via_jpaths(importee)
            self._via_jpaths[importee] = result
            return result


class ImportGraph:
    """The import graph of a workspace folder, built by `ImportGraphBuilder`."""

    root: Path
    jpaths: list[Path]

    # Edge fields
    imports: dict[Path, set[Path]]
    imported_by: dict[Path, set[Path]]

    malformed: list[Path]

    def __init__(self, root: Path, jpaths: list[Path]):
        self.root = root
        self.jpaths = jpaths

        self.imports = defaultdict(set)
        self.imported_by = defaultdict(set)

        self.malformed = []

    def add_edge(self, importer: Path, importee: Path):
        self.imports[importer].add(importee)
        self.imported_by[importee].add(importer)


class ImportGraphBuilder:
    """Builds an `ImportGraph` from scratch.

    Create one per bulk build and drop it afterwards. The resolution caches live only for
    the duration of `build`, so the finished graph doesn't keep them alive.
    """

    root: Path
    jpaths: list[Path]
    batch_size: int

    def __init__(self, root: Path, jpaths: list[Path], batch_size: int = 256):
        self.root = root
        self.jpaths = jpaths
        self.batch_size = batch_size

    def build(self, docs: list[Path]) -> ImportGraph:
        graph = ImportGraph(self.root, self.jpaths)
        resolver = CachedImportResolver(self.root, self.jpaths)
        parallelism = max(2, os.process_cpu_count() or 2)

        with ProcessPoolExecutor(max_workers=parallelism) as executor:
            raw_importees = itertools.zip_longest(
                docs,
                executor.map(collect_importees, docs, chunksize=self.batch_size),
            )

        for importer, (importees, error) in raw_importees:
            if error:
                graph.malformed.append(importer)
            else:
                for importee in importees:
                    if resolved := resolver.resolve(importer, importee):
                        graph.add_edge(importer, resolved)

        return graph
