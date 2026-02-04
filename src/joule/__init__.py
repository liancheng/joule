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
from joule.parsing import parse_jsonnet
from joule.server import server
from joule.util import maybe, head

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
    Scope = "s"


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
                - `s`: The Jsonnet variable scope tree
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
        case TreeType.Scope:
            scope = head(maybe(ast.var_scope))
            tree = PrettyScope(scope)

    Console(markup=False).print(tree)


@app.command()
def index(
    workspace_root: Annotated[
        Path,
        typer.Argument(
            help="The workspace root directory.",
            exists=True,
            file_okay=False,
            dir_okay=True,
            readable=True,
            allow_dash=False,
        ),
    ],
    path: Annotated[
        Path,
        typer.Argument(
            help="The Jsonnet file to index",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            allow_dash=False,
        ),
    ],
):
    del workspace_root
    cst = parse_jsonnet(path.read_text())
    ast = Document.from_cst(path.as_uri(), cst)
    ScopeResolver().resolve(ast)
