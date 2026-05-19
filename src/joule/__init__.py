import logging
import os
import sys
import time
from pathlib import Path
from typing import Annotated

from rich.console import Console
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
    _, failed = WorkspaceIndex(root.absolute()).load(parallelism)

    if failed:
        console = Console(stderr=True)
        console.print(f"Failed to parse {len(failed)} file(s):", style="red")
        for path in failed:
            console.print(f"  {path}", style="red")


if __name__ == "__main__":
    app()
