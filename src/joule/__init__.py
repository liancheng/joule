import logging
import sys
from pathlib import Path
from typing import Annotated

from rich.console import Console
from typer import Argument, Typer

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

    parse_document(source, uri)
    # Console(markup=False).print(parse_document(source, uri).pretty)


@app.command()
def index(
    root: Annotated[
        Path,
        Argument(help="The root of the workspace to index.", exists=True),
    ],
):
    suffixes = [".jsonnet", ".libsonnet", ".jsonnet.TEMPLATE"]
    docs = []

    def on_file(file: Path):
        if any(file.name.endswith(suffix) for suffix in suffixes):
            docs.append(file.read_text())

    def on_dir(dir: Path):
        return not dir.name.startswith(".") and not dir.name == "experimental"

    WorkspaceIndex(root.absolute().as_uri()).scan(on_file, on_dir)


if __name__ == "__main__":
    app()
