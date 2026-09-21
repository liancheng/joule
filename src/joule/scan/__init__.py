"""Reusable Jsonnet file discovery and parallel processing.

Both the ``scan`` and ``imports`` commands share the same shape: discover every
Jsonnet file under a root, then process each one in a worker pool while showing
a progress bar. That common machinery lives here so the commands can reuse it.
"""

import shutil
import subprocess
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import tree_sitter as ts
import tree_sitter_jsonnet
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    ProgressColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)

# Chunk work coarsely so per-task IPC overhead stays small on large scans.
_CHUNK_SIZE = 64

# The parsed language, shared by the worker parsers and by query compilation.
LANGUAGE = ts.Language(tree_sitter_jsonnet.language())


def discover_jsonnet_files(
    root: Path,
    extensions: list[str],
    ignore: list[str],
) -> list[Path]:
    fd = shutil.which("fd") or shutil.which("fdfind")

    if fd is None:
        raise RuntimeError(
            "`fd` is required to discover Jsonnet files but was not found on PATH"
        )

    command = [fd, "--type", "file"]

    for extension in extensions:
        command += ["--extension", extension]

    for pattern in ignore:
        command += ["--exclude", pattern]

    command += [".", str(root)]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=True,
    )

    return [Path(line) for line in result.stdout.splitlines() if line]


# Each worker process builds its own parser once -- parsers are neither
# picklable nor safe to share across processes -- and reuses it for every file.
_parser: ts.Parser | None = None


def init_worker() -> None:
    global _parser
    _parser = ts.Parser(LANGUAGE)


def parse(source: bytes) -> ts.Tree:
    """Parse ``source`` with this worker's parser (see :func:`init_worker`)."""
    assert _parser is not None, "worker parser was not initialized"
    return _parser.parse(source)


def run[T](
    files: list[Path],
    worker: Callable[[Path], T],
    *,
    jobs: int,
    description: str,
    extra_columns: Iterable[ProgressColumn] = (),
    fields: dict[str, object] | None = None,
    on_result: Callable[[T], dict[str, object] | None] | None = None,
) -> Iterator[T]:
    """Run ``worker`` over ``files`` in a process pool, showing a progress bar.

    Results are yielded in input order. ``on_result`` is called (in this
    process) with each result and may return task-field updates to display
    live -- e.g. a running tally rendered by one of ``extra_columns``.
    """
    columns: list[ProgressColumn] = [
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        *extra_columns,
    ]

    with (
        Progress(*columns) as progress,
        ProcessPoolExecutor(max_workers=jobs, initializer=init_worker) as pool,
    ):
        task = progress.add_task(description, total=len(files), **(fields or {}))

        for result in pool.map(worker, files, chunksize=_CHUNK_SIZE):
            updates = on_result(result) if on_result is not None else None
            progress.update(task, advance=1, **(updates or {}))
            yield result
