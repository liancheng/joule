import functools
import itertools
import os
import os.path as P
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import tree_sitter as ts

from joule.maybe import head_or_none, maybe
from joule.syntax import trees as T

__all__ = [
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
    root: Path
    jpaths: list[Path]

    _is_file: dict[str, bool]
    _same_dir: dict[tuple[str, str], str | None]
    _via_jpaths: dict[str, str | None]

    def __init__(self, root: Path, jpaths: list[Path]):
        self.root = root
        self.jpaths = jpaths

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

    def try_abs_path(self, importee) -> str | None:
        return importee if P.isabs(importee) else None

    def try_same_dir(self, importer: Path, importee: str) -> str | None:
        # Normalized so that different spellings of one importee share an entry.
        importer_dir = P.dirname(P.join(self.root, importer))
        importee = P.normpath(importee)

        try:
            return self._same_dir[(importer_dir, importee)]
        except KeyError:
            joined = P.join(importer_dir, importee)
            path = joined if self.is_file(joined) else None
            self._same_dir[(importer_dir, importee)] = path
            return path

    def try_jpaths(self, importee: str) -> str | None:
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

    def resolve(self, importer: Path, importee: str) -> Path | None:
        return head_or_none(
            Path(P.abspath(path))
            for path in maybe(
                self.try_abs_path(importee)
                or self.try_same_dir(importer, importee)
                or self.try_jpaths(importee)
            )
        )


class ImportGraph:
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
    root: Path
    jpaths: list[Path]
    batch_size: int

    def __init__(self, root: Path, jpaths: list[Path], batch_size: int = 256):
        self.root = root
        self.jpaths = jpaths
        self.batch_size = batch_size

    def build(self, docs: list[Path]) -> ImportGraph:
        graph = ImportGraph(self.root, self.jpaths)
        resolver = ImportResolver(self.root, self.jpaths)
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
