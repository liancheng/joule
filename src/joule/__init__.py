import functools
import os
from collections import Counter, defaultdict
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated

import tree_sitter as ts
import typer
from rich.progress import TextColumn
from tree_sitter import QueryCursor
from typer import Typer

from joule.scan import LANGUAGE, discover_jsonnet_files, parse, run
from joule.trees import Import, ImportKind, MalformedError

app = Typer(
    no_args_is_help=True,
    rich_markup_mode="markdown",
)

DEFAULT_EXTENSIONS = ["jsonnet", "libsonnet", "jsonnet.TEMPLATE"]
DEFAULT_IGNORE: list[str] = []
DEFAULT_JOBS = max(2, int(1.5 * (os.process_cpu_count() or 1)))
DEFAULT_JPATH: list[Path] = []

RootArg = Annotated[
    Path,
    typer.Argument(
        exists=True,
        file_okay=False,
        dir_okay=True,
        help="Directory to scan for Jsonnet files.",
    ),
]

ExtensionOpt = Annotated[
    list[str],
    typer.Option(
        "--extension",
        "-e",
        help="File extension to include. Repeat to include several.",
    ),
]

IgnoreOpt = Annotated[
    list[str],
    typer.Option(
        "--ignore",
        "-i",
        help="Glob of files or folders to ignore. Repeat to ignore several.",
    ),
]

JobsOpt = Annotated[
    int,
    typer.Option(
        "--jobs",
        "-j",
        min=1,
        help="Number of worker processes to parse with.",
    ),
]

JpathOpt = Annotated[
    list[Path],
    typer.Option(
        "--jpath",
        "-J",
        help=(
            "Library search path for import resolution (repeatable), like "
            "jsonnet's -J. JSONNET_PATH is also honored."
        ),
    ),
]


def _parse_file(path: Path) -> str:
    try:
        source = path.read_bytes()
    except OSError:
        return "unreadable"

    return "failed" if parse(source).root_node.has_error else "parsed"


@app.command()
def scan(
    root: RootArg = Path("."),
    extension: ExtensionOpt = DEFAULT_EXTENSIONS,
    ignore: IgnoreOpt = DEFAULT_IGNORE,
    jobs: JobsOpt = DEFAULT_JOBS,
):
    """Discover Jsonnet files under `root`, parse each one, and report results."""
    files = discover_jsonnet_files(root, extension, ignore)

    outcomes: Counter[str] = Counter()

    def tally(outcome: str) -> dict[str, object]:
        outcomes[outcome] += 1
        return {"parsed": outcomes["parsed"], "failed": outcomes["failed"]}

    for _ in run(
        files,
        _parse_file,
        jobs=jobs,
        description="Parsing",
        extra_columns=[
            TextColumn("parsed={task.fields[parsed]} failed={task.fields[failed]}")
        ],
        fields={"parsed": 0, "failed": 0},
        on_result=tally,
    ):
        pass

    typer.echo(f"{len(files)} Jsonnet file(s) found.")
    typer.echo(f"  {outcomes['parsed']} parsed successfully")
    typer.echo(f"  {outcomes['failed']} failed to parse")
    typer.echo(f"  {outcomes['unreadable']} could not be read")


# Matches every `import` / `importstr` / `importbin` node anywhere in the tree,
# so we can build only the `Import` nodes instead of the whole AST.
_IMPORT_QUERY = ts.Query(LANGUAGE, "(import) @import")


def _resolve_jpaths(jpath: list[Path]) -> tuple[Path, ...]:
    """Combine `-J` entries with `JSONNET_PATH`, normalized to absolute paths."""
    env = os.environ.get("JSONNET_PATH", "")
    from_env = [Path(entry) for entry in env.split(os.pathsep) if entry]
    return tuple(Path(os.path.abspath(base)) for base in (*jpath, *from_env))


def _try_path(base: Path, importee: str) -> Path | None:
    """Resolve `importee` against `base` the way Jsonnet's file importer does.

    An absolute import is used as-is; otherwise it is joined onto `base` and
    normalized *lexically* (Jsonnet does not follow symlinks). Returns the path
    only if it names an existing file.
    """
    candidate = Path(importee) if os.path.isabs(importee) else base / importee
    candidate = Path(os.path.abspath(candidate))
    return candidate if candidate.is_file() else None


def _extract_imports(path: Path, jpaths: tuple[Path, ...]) -> tuple[Path, list[Path]]:
    """Return the file's resolved path and the physical files it directly imports."""
    src = Path(os.path.abspath(path))

    try:
        source = path.read_bytes()
    except OSError:
        return src, []

    importees: list[Path] = []
    seen: set[Path] = set()

    captures = QueryCursor(_IMPORT_QUERY).captures(parse(source).root_node)
    for node in captures.get("import", []):
        try:
            imp = Import.from_cst(node)
        except (MalformedError, ValueError):
            # A malformed import (e.g. within a file with syntax errors); skip it.
            continue

        # Only plain `import` builds an import chain; `importstr` / `importbin`
        # pull in text/bytes, not further Jsonnet, so they are excluded.
        if imp.kind is not ImportKind.Default:
            continue

        # Jsonnet tries the importing file's own directory first, then each
        # library search path (later `-J` entries win, so try them in reverse).
        target = _try_path(path.parent, imp.importee.value)
        if target is None:
            for base in reversed(jpaths):
                target = _try_path(base, imp.importee.value)
                if target is not None:
                    break

        if target is not None and target not in seen:
            seen.add(target)
            importees.append(target)

    return src, importees


def _longest_import_chain(imports_map: dict[Path, list[Path]]) -> list[Path]:
    """Return the files on a longest chain of direct imports.

    This is the longest path in the import graph. It is computed with an
    iterative (stack-based) DFS so deep chains cannot overflow the recursion
    limit, and any cycle's back-edges are ignored rather than followed forever.
    """
    length: dict[Path, int] = {}  # longest chain, in files, starting at a node
    successor: dict[Path, Path | None] = {}  # next node on that longest chain
    on_stack: set[Path] = set()

    for start, targets in imports_map.items():
        if start in length:
            continue

        stack: list[tuple[Path, Iterator[Path]]] = [(start, iter(targets))]
        on_stack.add(start)

        while stack:
            node, pending = stack[-1]

            for target in pending:
                if target in on_stack or target in length:
                    # A back-edge (cycle) or an already-finalized node; either
                    # way it is folded in when `node` is finalized below.
                    continue
                stack.append((target, iter(imports_map.get(target, ()))))
                on_stack.add(target)
                break
            else:
                best_len, best_next = 0, None
                for target in imports_map.get(node, ()):
                    if target in length and length[target] > best_len:
                        best_len, best_next = length[target], target

                length[node] = best_len + 1
                successor[node] = best_next
                on_stack.discard(node)
                stack.pop()

    if not length:
        return []

    node: Path | None = max(length, key=lambda n: length[n])
    chain: list[Path] = []
    while node is not None:
        chain.append(node)
        node = successor.get(node)

    return chain


@app.command()
def imports(
    root: RootArg = Path("."),
    extension: ExtensionOpt = DEFAULT_EXTENSIONS,
    ignore: IgnoreOpt = DEFAULT_IGNORE,
    jobs: JobsOpt = DEFAULT_JOBS,
    jpath: JpathOpt = DEFAULT_JPATH,
):
    """Build the direct-import graph across all Jsonnet files under `root`."""
    files = discover_jsonnet_files(root, extension, ignore)
    jpaths = _resolve_jpaths(jpath)

    # path -> files it directly imports; path -> files that directly import it.
    imports_map: dict[Path, list[Path]] = {}
    imported_by: dict[Path, set[Path]] = defaultdict(set)

    worker = functools.partial(_extract_imports, jpaths=jpaths)
    for src, targets in run(
        files, worker, jobs=jobs, description="Extracting imports"
    ):
        imports_map[src] = targets
        for target in targets:
            imported_by[target].add(src)

    root_abs = Path(os.path.abspath(root))

    def rel(path: Path) -> str:
        try:
            return str(path.relative_to(root_abs))
        except ValueError:
            return str(path)

    edges = sum(len(targets) for targets in imports_map.values())
    with_imports = sum(1 for targets in imports_map.values() if targets)
    chain = _longest_import_chain(imports_map)

    typer.echo(f"{len(files)} Jsonnet file(s) scanned.")
    typer.echo(f"  {with_imports} import at least one file")
    typer.echo(f"  {edges} direct import edges")
    typer.echo(f"  {len(imported_by)} file(s) imported by others")
    typer.echo(f"  longest import chain: {len(chain)} file(s)")

    top = sorted(imported_by.items(), key=lambda kv: len(kv[1]), reverse=True)[:10]
    if top:
        typer.echo("Most imported:")
        for target, importers in top:
            typer.echo(f"  {len(importers):>5}  {rel(target)}")

    if len(chain) > 1:
        typer.echo("Longest import chain:")
        for depth, node in enumerate(chain):
            typer.echo(f"  {'→ ' if depth else '  '}{rel(node)}")


if __name__ == "__main__":
    app()
