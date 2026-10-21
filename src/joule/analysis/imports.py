import functools
import os
import os.path as P
from collections import defaultdict
from collections.abc import Callable, Iterable
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import override

import tree_sitter as ts

from joule.maybe import head_or_none, maybe
from joule.syntax import trees as T

__all__ = [
    "ImportGraph",
    "ImportGraphBuilder",
    "ImportResolver",
    "ParallelImportGraphBuilder",
]


@functools.cache
def import_cursor() -> ts.QueryCursor:
    # Compiling the query once per worker process (it costs ~66 µs each time).
    query = ts.Query(T.language(), "(import) @import")
    return ts.QueryCursor(query)


type Importees = tuple[list[str], bool]

type ImporteesCollector = Callable[[Path], Importees]


def collect_importees(path: Path) -> Importees:
    try:
        source = path.read_bytes()
    except OSError:
        return [], True

    root_node = T.parse(source).root_node

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
        importer_dir = P.dirname(P.join(self.root, importer))

        try:
            return self._same_dir[(importer_dir, importee)]
        except KeyError:
            joined = P.join(importer_dir, importee)
            path = P.abspath(joined) if self.is_file(joined) else None
            return self._same_dir.setdefault((importer_dir, importee), path)

    def try_jpaths(self, importee: str) -> str | None:
        try:
            return self._via_jpaths[importee]
        except KeyError:
            result = head_or_none(
                P.abspath(path)
                for jpath in reversed(self.jpaths)
                if self.is_file(path := P.join(self.root, jpath, importee))
            )
            self._via_jpaths[importee] = result
            return result

    def resolve(self, importer: Path, importee: str) -> Path | None:
        return head_or_none(
            Path(path)
            for path in maybe(
                self.try_abs_path(importee)
                or self.try_same_dir(importer, P.normpath(importee))
                or self.try_jpaths(P.normpath(importee))
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


type MapFn = Callable[
    [ImporteesCollector, list[Path]],
    Iterable[Importees],
]


class ImportGraphBuilder:
    root: Path
    jpaths: list[Path]

    def __init__(self, root: Path, jpaths: list[Path]):
        self.root = root
        self.jpaths = jpaths

    def build(self, docs: list[Path]) -> ImportGraph:
        return self.do_build(docs, map)

    def do_build(self, docs: list[Path], map_fn: MapFn) -> ImportGraph:
        graph = ImportGraph(self.root, self.jpaths)
        resolver = ImportResolver(self.root, self.jpaths)
        importees_of = map_fn(collect_importees, docs)

        for importer, (importees, error) in zip(docs, importees_of, strict=True):
            if error:
                graph.malformed.append(importer)

            for importee in importees:
                if resolved := resolver.resolve(importer, importee):
                    graph.add_edge(importer, resolved)

        return graph


class ParallelImportGraphBuilder(ImportGraphBuilder):
    batch_size: int

    def __init__(self, root: Path, jpaths: list[Path], batch_size: int = 256):
        super().__init__(root, jpaths)
        self.batch_size = batch_size

    @override
    def build(self, docs: list[Path]) -> ImportGraph:
        parallelism: int = max(2, os.process_cpu_count() or 2)

        with ProcessPoolExecutor(max_workers=parallelism) as executor:
            map_fn: MapFn = functools.partial(executor.map, chunksize=self.batch_size)
            return self.do_build(docs, map_fn)
