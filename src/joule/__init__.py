import logging
import os
import sys
import time
from pathlib import Path
from typing import Annotated

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from typer import Argument, Option, Typer

from joule.parsers.jsonnet import parse_document
from joule.services.workspace_index import WorkspaceIndex

app = Typer(
    no_args_is_help=True,
    rich_markup_mode="markdown",
)

logging.basicConfig(
    filename="/tmp/pygls.log",
    filemode="w",
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s:%(name)s %(message)s",
)

sys.setrecursionlimit(1024 * 1024)


@app.command()
def tree(
    path: Annotated[
        Path,
        Argument(
            help="The Jsonnet file to print.",
            exists=True,
            dir_okay=False,
            allow_dash=True,
        ),
    ],
):
    source, uri = (
        (sys.stdin.read(), "dev/stdin")
        if path == Path("-")
        else (path.read_text(), path.absolute().as_uri())
    )

    Console(markup=False).print(parse_document(source, uri).pretty)


@app.command()
def index(
    root: Annotated[
        Path,
        Argument(help="The root of the workspace to index.", exists=True),
    ],
    parallelism: Annotated[
        int,
        Option(
            "-p",
            "--parallelism",
            help="Number of worker processes used for parsing.",
        ),
    ] = os.cpu_count() or 1,
):

    index = WorkspaceIndex(root.absolute())

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
    ) as progress:
        task = progress.add_task("Discovering source files...", total=None)
        sources = index.discover(advance=lambda n: progress.advance(task, n))
        progress.update(task, total=len(sources))

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
    ) as progress:
        task = progress.add_task("Parsing source files...", total=len(sources))
        _, failed = index.load(
            sources,
            parallelism,
            advance=lambda n: progress.advance(task, n),
        )

    for path in failed:
        print(path)


if __name__ == "__main__":
    app()
