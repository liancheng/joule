import functools
import os
import os.path as P
import sys
from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator
from collections.abc import Set as AbstractSet
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Self, override

import tree_sitter as ts

from joule.maybe import head_or_none, maybe
from joule.syntax import trees as T

__all__ = [
    "ImportGraph",
    "ImportResolver",
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

    _is_file_cache: dict[str, bool]
    _same_dir_cache: dict[tuple[str, str], str | None]
    _via_jpaths_cache: dict[str, str | None]

    def __init__(self, root: Path, jpaths: list[Path]):
        self.root = root
        self.jpaths = jpaths

        self._is_file_cache = {}
        self._same_dir_cache = {}
        self._via_jpaths_cache = {}

    def _is_file(self, path: str) -> bool:
        path = P.abspath(path)
        try:
            return self._is_file_cache[path]
        except KeyError:
            result = P.isfile(path)
            self._is_file_cache[path] = result
            return result

    def _try_abs_path(self, importee) -> str | None:
        return importee if P.isabs(importee) else None

    def _try_same_dir(self, importer: Path, importee: str) -> str | None:
        importer_dir = P.dirname(P.join(self.root, importer))

        try:
            return self._same_dir_cache[(importer_dir, importee)]
        except KeyError:
            joined = P.join(importer_dir, importee)
            path = P.abspath(joined) if self._is_file(joined) else None
            return self._same_dir_cache.setdefault((importer_dir, importee), path)

    def _try_jpaths(self, importee: str) -> str | None:
        try:
            return self._via_jpaths_cache[importee]
        except KeyError:
            result = head_or_none(
                P.abspath(path)
                for jpath in reversed(self.jpaths)
                if self._is_file(path := P.join(self.root, jpath, importee))
            )
            self._via_jpaths_cache[importee] = result
            return result

    def resolve(self, importer: Path, importee: str) -> Path | None:
        return head_or_none(
            Path(path)
            for path in maybe(
                self._try_abs_path(importee)
                or self._try_same_dir(importer, P.normpath(importee))
                or self._try_jpaths(P.normpath(importee))
            )
        )


type ImporteesMapper = Callable[
    [ImporteesCollector, list[Path]],
    Iterable[Importees],
]


def discard_from[K, V](index: dict[K, set[V]], key: K, value: V):
    if (values := index.get(key)) is not None:
        values.discard(value)

        if len(values) == 0:
            del index[key]


class ImportGraph:
    """The imports between the files of a workspace folder.

    Build a graph with `build` or `build_in_parallel`. Then keep it current with
    `file_created`, `file_changed`, and `file_deleted`.
    """

    _root: Path
    _jpaths: list[Path]

    # Edges
    _imports: dict[Path, set[Path]]
    _imported_by: dict[Path, set[Path]]

    # Indices for incremental updates
    _importees: dict[Path, set[str]]
    _basename_imported_by: dict[str, set[Path]]

    _malformed: set[Path]

    def __init__(self, root: Path, jpaths: list[Path]):
        self._root = root
        self._jpaths = jpaths

        self._imports = defaultdict(set)
        self._imported_by = defaultdict(set)

        self._importees = defaultdict(set)
        self._basename_imported_by = defaultdict(set)

        self._malformed = set()

    @classmethod
    def build(cls, root: Path, jpaths: list[Path], docs: Iterable[Path]) -> Self:
        return cls._build(root, jpaths, docs, map)

    @classmethod
    def build_in_parallel(
        cls,
        root: Path,
        jpaths: list[Path],
        docs: Iterable[Path],
        *,
        batch_size: int = 256,
    ) -> Self:
        parallelism = max(2, os.process_cpu_count() or 2)

        with ProcessPoolExecutor(max_workers=parallelism) as executor:
            mapper = functools.partial(executor.map, chunksize=batch_size)
            return cls._build(root, jpaths, docs, mapper)

    def imports_of(self, path: Path) -> AbstractSet[Path]:
        return self._imports.get(path, frozenset())

    def importers_of(self, path: Path) -> AbstractSet[Path]:
        return self._imported_by.get(path, frozenset())

    def edges(self) -> Iterator[tuple[Path, Path]]:
        return (
            (importer, importee)
            for importer, importees in self._imports.items()
            for importee in importees
        )

    @property
    def malformed(self) -> AbstractSet[Path]:
        return self._malformed

    @property
    def pretty(self) -> str:
        """Returns all the data of the graph as sorted text, for tests and debugging.

        Paths under the root are relative to the root.
        """

        def show(value: Path | str) -> str:
            match value:
                case Path() if value.is_relative_to(self._root):
                    return str(value.relative_to(self._root))
                case Path():
                    return str(value)
                case _:
                    return repr(value)

        sections: dict[str, dict] = {
            "imports": self._imports,
            "imported by": self._imported_by,
            "importees": self._importees,
            "file names": self._basename_imported_by,
        }

        lines = [
            line
            for title, index in sections.items()
            for line in [
                f"{title}:",
                *sorted(
                    f"  {show(key)}: {show(value)}"
                    for key, values in index.items()
                    for value in values
                ),
            ]
        ]

        lines += ["malformed:", *sorted(f"  {show(path)}" for path in self._malformed)]
        return "\n".join(lines) + "\n"

    @override
    def __repr__(self) -> str:
        edges = sum(map(len, self._imports.values()))
        malformed = len(self._malformed)
        return f"ImportGraph(root={str(self._root)!r}, {edges} edges, {malformed} malformed)"

    @override
    def __eq__(self, other: object) -> bool:
        match other:
            case ImportGraph():
                return (
                    (self._root, self._jpaths) == (other._root, other._jpaths)
                    and self._imports == other._imports
                    and self._imported_by == other._imported_by
                    and self._importees == other._importees
                    and self._basename_imported_by == other._basename_imported_by
                    and self._malformed == other._malformed
                )
            case _:
                return NotImplemented

    def file_created(self, path: Path):
        """Resolves again the imports that the new file can change.

        A new file can shadow a candidate with a lower priority, or make an unresolved
        import resolve. This applies to all files, also to files that are not documents.
        If the new file is a document, also call `file_changed`.
        """
        # Each candidate of an importee ends with the file name of the importee. Thus
        # only the imports with the same file name can change.
        importers = set(self._basename_imported_by.get(P.basename(path), ()))
        resolver = self._resolver()

        for importer in importers:
            self._resolve_again(importer, resolver)

    def file_changed(self, path: Path):
        """Collects the imports of the document again. Also use it for a new document."""
        importees, malformed = collect_importees(path)
        self._remove_document(path)
        self._add_document(path, importees, malformed, self._resolver())

    def file_deleted(self, path: Path):
        # The imports of the file can now resolve to a candidate with a lower priority.
        importers = self._imported_by.get(path, set()) - {path}
        self._remove_document(path)
        resolver = self._resolver()

        for importer in importers:
            self._resolve_again(importer, resolver)

    @classmethod
    def _build(
        cls,
        root: Path,
        jpaths: list[Path],
        docs: Iterable[Path],
        mapper: ImporteesMapper,
    ) -> Self:
        graph = cls(root, jpaths)
        resolver = graph._resolver()
        docs = list(docs)
        importees_of = mapper(collect_importees, docs)

        for doc, (importees, malformed) in zip(docs, importees_of, strict=True):
            graph._add_document(doc, importees, malformed, resolver)

        return graph

    def _resolver(self) -> ImportResolver:
        # The caches of a resolver become incorrect when somebody creates or deletes a
        # file. Thus each build and each event uses a new resolver.
        return ImportResolver(self._root, self._jpaths)

    def _add_document(
        self,
        path: Path,
        importees: list[str],
        malformed: bool,
        resolver: ImportResolver,
    ):
        if malformed:
            self._malformed.add(path)

        for importee in map(sys.intern, importees):
            self._importees[path].add(importee)
            self._basename_imported_by[P.basename(importee)].add(path)

            if (resolved := resolver.resolve(path, importee)) is not None:
                self._imports[path].add(resolved)
                self._imported_by[resolved].add(path)

    def _remove_document(self, path: Path):
        for importee in self._imports.pop(path, set()):
            discard_from(self._imported_by, importee, path)

        for importee in self._importees.pop(path, set()):
            discard_from(self._basename_imported_by, P.basename(importee), path)

        self._malformed.discard(path)

    def _resolve_again(self, importer: Path, resolver: ImportResolver):
        resolved = {
            path
            for importee in self._importees.get(importer, set())
            for path in maybe(resolver.resolve(importer, importee))
        }

        before = self._imports.pop(importer, set())

        for importee in before - resolved:
            discard_from(self._imported_by, importee, importer)

        for importee in resolved - before:
            self._imported_by[importee].add(importer)

        if resolved:
            self._imports[importer] = resolved
