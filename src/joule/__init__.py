import logging
import sys
from enum import StrEnum
from pathlib import Path
from textwrap import dedent
from typing import Annotated

import typer
from rich.console import Console

from joule.ast import Document, PrettyAST, PrettyCST, PrettyScope
from joule.model import ScopeResolver
from joule.model.document_loader import DocumentLoader
from joule.parsing import parse_jsonnet
from joule.server import server

app = typer.Typer(
    no_args_is_help=True,
    rich_markup_mode="markdown",
)

logging.basicConfig(
    filename="/tmp/pygls.log",
    filemode="w",
    level=logging.DEBUG,
)


@app.command()
def serve():
    server.start_io()


class TreeType(StrEnum):
    Jsonnet = "j"
    TreeSitter = "t"
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

    cst = parse_jsonnet(source)
    ast = Document.from_cst(uri, cst)
    ScopeResolver().resolve(ast)

    match tree_type:
        case TreeType.Jsonnet:
            tree = PrettyAST(ast)
        case TreeType.TreeSitter:
            tree = PrettyCST(cst)
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
    def resolve(file: Path):
        cst = parse_jsonnet(file.read_text())
        ast = Document.from_cst(file.as_uri(), cst)
        ScopeResolver().resolve(ast)

    path = path.absolute()

    def run():
        if path.is_file():
            resolve(path)
        else:
            for tree in DocumentLoader(path.as_uri()).load_all(path):
                print(tree.location.uri)

    if profile:
        import cProfile

        with cProfile.Profile() as prof:
            run()

        prof.dump_stats(profile.as_posix())
    else:
        run()


if __name__ == "__main__":
    app()
