import os
import shutil
import subprocess
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Annotated

import tree_sitter as ts
import tree_sitter_jsonnet
import typer
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from typer import Typer

app = Typer(
    no_args_is_help=True,
    rich_markup_mode="markdown",
)

DEFAULT_EXTENSIONS = ["jsonnet", "libsonnet"]
DEFAULT_IGNORE: list[str] = []

# Each worker process builds its own parser once -- parsers are neither
# picklable nor safe to share across processes -- and reuses it for every file
# it handles.
_parser: ts.Parser | None = None


def _init_worker() -> None:
    global _parser
    _parser = ts.Parser(ts.Language(tree_sitter_jsonnet.language()))


def _parse_file(path: Path) -> str:
    assert _parser is not None, "worker parser was not initialized"

    try:
        source = path.read_bytes()
    except OSError:
        return "unreadable"

    return "failed" if _parser.parse(source).root_node.has_error else "parsed"


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


@app.command()
def scan(
    root: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=False,
            dir_okay=True,
            help="Directory to scan for Jsonnet files.",
        ),
    ] = Path("."),
    extension: Annotated[
        list[str],
        typer.Option(
            "--extension",
            "-e",
            help="File extension to include. Repeat to include several.",
        ),
    ] = DEFAULT_EXTENSIONS,
    ignore: Annotated[
        list[str],
        typer.Option(
            "--ignore",
            "-i",
            help="Glob of files or folders to ignore. Repeat to ignore several.",
        ),
    ] = DEFAULT_IGNORE,
    jobs: Annotated[
        int,
        typer.Option(
            "--jobs",
            "-j",
            min=1,
            help="Number of worker processes to parse with.",
        ),
    ] = max(2, int(1.5 * (os.process_cpu_count() or 1))),
):
    """Discover Jsonnet files under `root`, parse each one, and report results."""
    files = discover_jsonnet_files(root, extension, ignore)

    outcomes: Counter[str] = Counter()

    progress = Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        TextColumn("parsed={task.fields[parsed]} failed={task.fields[failed]}"),
    )

    with (
        progress,
        ProcessPoolExecutor(max_workers=jobs, initializer=_init_worker) as pool,
    ):
        task = progress.add_task("Parsing", total=len(files), parsed=0, failed=0)

        for outcome in pool.map(_parse_file, files, chunksize=64):
            outcomes[outcome] += 1
            progress.update(
                task,
                advance=1,
                parsed=outcomes["parsed"],
                failed=outcomes["failed"],
            )

    typer.echo(f"{len(files)} Jsonnet file(s) found.")
    typer.echo(f"  {outcomes['parsed']} parsed successfully")
    typer.echo(f"  {outcomes['failed']} failed to parse")
    typer.echo(f"  {outcomes['unreadable']} could not be read")


if __name__ == "__main__":
    app()
