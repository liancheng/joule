import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from functools import reduce
from itertools import batched
from os.path import isfile
from pathlib import Path
from textwrap import dedent
from typing import Annotated, Iterable

from lsprotocol.types import DefinitionResponse
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
    uri, source = (
        ("dev/stdin", sys.stdin.read())
        if path == Path("-")
        else (path.absolute().as_uri(), path.read_text())
    )

    Console(markup=False).print(parse_document(source, uri).pretty)


@app.command()
def index(
    root: Annotated[
        Path,
        Argument(
            help="The root of the workspace to index.",
            exists=True,
            file_okay=False,
        ),
    ],
):
    files = []
    suffixes = [".jsonnet", ".libsonnet", ".jsonnet.TEMPLATE"]

    def on_file(file: Path):
        if any(file.name.endswith(suffix) for suffix in suffixes):
            files.append(file)

    def on_dir(dir: Path):
        return not dir.name.startswith(".") and not dir.name == "experimental"

    WorkspaceIndex(root.absolute().as_uri()).scan(on_file, on_dir)

    print(len(files))

    def batch_parse(files: Iterable[Path]):
        return {
            path.as_uri(): parse_document(path.read_text(), path.as_uri())
            for path in list(files)
        }

    with ThreadPoolExecutor() as pool:
        docs = reduce(
            lambda a, b: a | b,
            pool.map(batch_parse, batched(files, 1000)),
        )

        print(len(docs))


if __name__ == "__main__":
    app()
