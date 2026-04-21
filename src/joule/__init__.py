import logging
import sys
from enum import StrEnum
from pathlib import Path
from textwrap import dedent
from typing import Annotated

import typer
from rich.console import Console

from joule.ast import Document, PrettyAST, PrettyCST, PrettyScope
from joule.config import JouleConfig
from joule.model import DocumentStore, ScopeResolver
from joule.parsing2 import Parser
from joule.server import server

app = typer.Typer(
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
def serve():
    server.start_io()


class TreeType(StrEnum):
    Jsonnet = "j"
    VarScope = "v"


@app.command()
def tree(
    path: Annotated[
        Path,
        typer.Argument(
            help="The Jsonnet file to print.",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            writable=False,
            allow_dash=True,
        ),
    ],
    tree_type: Annotated[
        TreeType,
        typer.Option(
            "-t",
            "--tree-type",
            help=dedent(
                """\
                The type of tree to print:
                - `j`: The Jsonnet AST
                - `t`: The tree-sitter CST
                - `v`: The Jsonnet variable scope tree
                """
            ),
        ),
    ] = TreeType.Jsonnet,
):
    if path == Path("-"):
        uri = "/dev/stdin"
        source = sys.stdin.read()
    else:
        uri = path.absolute().as_uri()
        source = path.read_text()

    ast = Parser(uri).document.parse(source)
    ScopeResolver().resolve(ast)

    match tree_type:
        case TreeType.Jsonnet:
            tree = PrettyAST(ast)
        case TreeType.VarScope:
            tree = PrettyScope(ast.top_level_scope)

    Console(markup=False).print(tree)


@app.command()
def index(
    path: Annotated[
        Path,
        typer.Argument(
            help="The Jsonnet file to index",
            exists=True,
            file_okay=True,
            dir_okay=True,
            readable=True,
            allow_dash=False,
        ),
    ],
    config_path: Annotated[
        Path | None,
        typer.Option(
            "-c",
            "--config",
            help="The Joule configuration file path.",
            file_okay=True,
            dir_okay=False,
            exists=True,
            readable=True,
        ),
    ] = None,
    profile: Annotated[
        Path | None,
        typer.Option(
            "-p",
            "--profile",
            help="Run the command with cProfile.",
            file_okay=True,
            dir_okay=False,
            writable=True,
            allow_dash=False,
        ),
    ] = None,
):
    path = path.absolute()
    workspace_path = path.parent if path.is_file() else path

    if config_path is None:
        config = JouleConfig()
    else:
        import json

        config = JouleConfig(**json.loads(config_path.read_text()))

    loader = DocumentStore(config, workspace_path.as_uri())

    def run():
        loader.load_workspace()

    if profile:
        import cProfile

        with cProfile.Profile() as prof:
            run()

        prof.dump_stats(profile.as_posix())
    else:
        run()


if __name__ == "__main__":
    app()
