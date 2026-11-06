import functools
import os
import os.path as P
import sys
from collections import defaultdict
from collections.abc import Callable, Iterable
from collections.abc import Set as AbstractSet
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Self, override

import tree_sitter as ts
from gitignore_parser import parse_gitignore_str

from joule.analysis.sources import discover_sources
from joule.config import SourcesConfig
from joule.maybe import maybe, optional
from joule.syntax import trees as T

__all__ = [
    "ImportGraph",
    "ImportResolver",
    "is_source",
]


@functools.cache
def import_cursor() -> ts.QueryCursor:
    # Compiling the query once per worker process (it costs ~66 µs each time).
    query = ts.Query(T.language(), "(import) @import")
    return ts.QueryCursor(query)


type Importees = dict[str, Path | None]


def collect_importees(path: Path, resolver: ImportResolver) -> Importees:
    try:
        source = path.read_bytes()
    except OSError:
        return {}

    root_node = T.parse(source).root_node

    def get_import_or_none(node: ts.Node) -> T.Import | None:
        try:
            return T.Import.from_cst(node)
        except T.MalformedError, ValueError:
            return None

    return {
        (raw := import_.importee.value): resolver.resolve(path, raw)
        for node in import_cursor().captures(root_node).get("import", [])
        for import_ in maybe(get_import_or_none(node))
        if import_.kind == T.ImportKind.Default
    }


@functools.cache
def exclusion_matcher(root: Path, patterns: tuple[str, ...]) -> Callable[[str], bool]:
    return parse_gitignore_str("\n".join(patterns), root)


def is_source(config: SourcesConfig, root: Path, path: Path) -> bool:
    excluded = exclusion_matcher(root, tuple(config.exclude))
    return (
        path.is_relative_to(root)
        and path.is_file()
        and not path.is_symlink()
        and not excluded(path.as_posix())
        and any(path.name.endswith(f".{ext}") for ext in config.extensions)
    )


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

    def resolve(self, importer: Path, importee: str) -> Path | None:
        return optional(
            Path(path)
            for path in maybe(
                self._try_abs_path(importee)
                or self._try_same_dir(importer, P.normpath(importee))
                or self._try_jpaths(P.normpath(importee))
            )
        )

    def _try_abs_path(self, importee) -> str | None:
        return importee if P.isabs(importee) else None

    def _try_same_dir(self, importer: Path, importee: str) -> str | None:
        """Looks for the importee under the same directory the importer belongs to."""
        importer_dir = P.dirname(P.join(self.root, importer))

        try:
            return self._same_dir_cache[(importer_dir, importee)]
        except KeyError:
            joined = P.join(importer_dir, importee)
            path = P.abspath(joined) if self._is_file(joined) else None
            return self._same_dir_cache.setdefault((importer_dir, importee), path)

    def _is_file(self, path: str) -> bool:
        path = P.abspath(path)
        try:
            return self._is_file_cache[path]
        except KeyError:
            result = P.isfile(path)
            self._is_file_cache[path] = result
            return result

    def _try_jpaths(self, importee: str) -> str | None:
        """Looks for the importee under jpath folders."""
        try:
            return self._via_jpaths_cache[importee]
        except KeyError:
            result = optional(
                P.abspath(path)
                for jpath in reversed(self.jpaths)
                if self._is_file(path := P.join(self.root, jpath, importee))
            )
            self._via_jpaths_cache[importee] = result
            return result


type ImporteesCollector = Callable[[Path], Importees]

type ImporteesMapper = Callable[
    [ImporteesCollector, list[Path]],
    Iterable[Importees],
]


class ImportGraph:
    _root: Path
    _config: SourcesConfig

    # Maps each importer to the absolute paths its imports resolve to. Unresolved
    # imports are left out.
    _imports: dict[Path, set[Path]]

    # The reverse of `_imports`: maps each file to the importers that import it.
    _imported_by: dict[Path, set[Path]]

    # Maps each importer to its raw importee strings, unresolved ones included.
    _raw_importees: dict[Path, set[str]]

    # Maps a file name to the importers with a raw importee of that name, whatever file
    # the importee resolves to, if any.
    _file_name_imported_by: dict[str, set[Path]]

    def __init__(self, root: Path, config: SourcesConfig):
        self._root = root
        self._config = config

        self._imports = defaultdict(set[Path])
        self._imported_by = defaultdict(set[Path])

        self._raw_importees = defaultdict(set[str])
        self._file_name_imported_by = defaultdict(set[Path])

    @classmethod
    def build(cls, root: Path, config: SourcesConfig) -> Self:
        return cls._build(root, config, map)

    @classmethod
    def build_in_parallel(
        cls,
        root: Path,
        config: SourcesConfig,
        *,
        batch_size: int = 256,
    ) -> Self:
        parallelism = max(2, os.process_cpu_count() or 2)

        with ProcessPoolExecutor(max_workers=parallelism) as executor:
            mapper = functools.partial(executor.map, chunksize=batch_size)
            return cls._build(root, config, mapper)

    def imports_of(self, path: Path) -> AbstractSet[Path]:
        return self._imports.get(path, frozenset())

    def importers_of(self, path: Path) -> AbstractSet[Path]:
        return self._imported_by.get(path, frozenset())

    def on_file_created(self, path: Path):
        # A new file can shadow the current target of an importee. When a file is
        # created, find all the files that import a file with the same name. Then
        # resolve their importees again.
        #
        # For example, jpaths is `lib`. The importee `f2.libsonnet` in `app/f1.jsonnet`
        # resolves to `lib/f2.libsonnet`:
        #
        #   // app/f1.jsonnet
        #   import "f2.libsonnet"
        #
        #   // lib/f2.libsonnet
        #   1
        #
        # Then create the file `app/f2.libsonnet`:
        #
        #   // app/f2.libsonnet
        #   2
        #
        # Now the importee resolves to the new file. A file in the folder of the
        # importer has a higher priority than a file in jpaths.

        importers = set(self._file_name_imported_by.get(P.basename(path), ()))
        resolver = ImportResolver(self._root, self._config.jpaths)

        for importer in importers:
            self._refresh(importer, resolver)

        self.on_file_changed(path)

    def on_file_changed(self, path: Path):
        if is_source(self._config, self._root, path):
            resolver = ImportResolver(self._root, self._config.jpaths)
            importees = collect_importees(path, resolver)
            self._sync_imports(path, importees)

    def on_file_deleted(self, path: Path):
        importers = self.importers_of(path) - {path}
        resolver = ImportResolver(self._root, self._config.jpaths)
        self._sync_imports(path, {})

        for importer in importers:
            self._refresh(importer, resolver)

    @property
    def pretty(self) -> str:
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
            "raw importees": self._raw_importees,
            "file names": self._file_name_imported_by,
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

        return "\n".join(lines) + "\n"

    def __len__(self) -> int:
        # Number of edges in the import graph.
        return sum(map(len, self._imports.values()))

    @override
    def __repr__(self) -> str:
        return f"ImportGraph(root={str(self._root)!r}, {len(self)} edges)"

    @override
    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, ImportGraph)
            and self._root == other._root
            and self._config == other._config
            and self._imports == other._imports
            and self._imported_by == other._imported_by
            and self._raw_importees == other._raw_importees
            and self._file_name_imported_by == other._file_name_imported_by
        )

    @classmethod
    def _build(cls, root: Path, config: SourcesConfig, mapper: ImporteesMapper) -> Self:
        graph = cls(root, config)
        sources = discover_sources(config, root)
        resolver = ImportResolver(root, config.jpaths)
        collect_fn = functools.partial(collect_importees, resolver=resolver)

        for importer, importees in zip(sources, mapper(collect_fn, sources)):
            graph._sync_imports(importer, importees)

        return graph

    def _sync_imports(self, importer: Path, importees: Importees):
        # Removes a source file from the import graph.
        for importee in self._imports.pop(importer, set()):
            self._discard(self._imported_by, importee, importer)

        for importee in self._raw_importees.pop(importer, set()):
            self._discard(self._file_name_imported_by, P.basename(importee), importer)

        for raw, resolved in importees.items():
            raw = sys.intern(raw)
            self._raw_importees[importer].add(raw)
            self._file_name_imported_by[P.basename(raw)].add(importer)

            if resolved is not None:
                self._imports[importer].add(resolved)
                self._imported_by[resolved].add(importer)

    def _refresh(self, path: Path, resolver: ImportResolver):
        """Re-resolves imports in a source file pointed by `path`.

        This method does not re-parse the source file, so the content of the source file
        must not have changed since the last time it was resolved.
        """
        importees = {
            raw: resolver.resolve(path, raw)
            for raw in self._raw_importees.get(path, set())
        }

        self._sync_imports(path, importees)

    def _discard[K, V](self, index: dict[K, set[V]], key: K, value: V):
        if (values := index.get(key)) is not None:
            values.discard(value)

            if len(values) == 0:
                del index[key]
