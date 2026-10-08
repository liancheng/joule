import time
from pathlib import Path
from textwrap import dedent
from typing import Annotated

import typer
from lsprotocol.types import WorkspaceFolder
from typer import Typer

from joule.analysis.imports import ImportGraph
from joule.providers import WorkspaceService
from joule.server import server

app = Typer(
    no_args_is_help=True,
    rich_markup_mode="markdown",
)

DEFAULT_EXTENSIONS = ["jsonnet", "libsonnet", "jsonnet.TEMPLATE"]
DEFAULT_IGNORE = [".git"]


@app.command()
def serve():
    server.start_io()


@app.command()
def benchmark(
    root: Annotated[
        Path,
        typer.Argument(
            help="The workspace root path.",
            exists=True,
            readable=True,
            dir_okay=True,
            file_okay=False,
        ),
    ],
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
    malformed_output: Annotated[
        Path,
        typer.Option(
            "--malformed-output",
            help="File to write the absolute paths of documents that failed to parse.",
        ),
    ] = Path("malformed.txt"),
):
    """Benchmark discovering Jsonnet files and building the import graph."""
    root = root.absolute()
    workspace_service = WorkspaceService(WorkspaceFolder(root.as_uri(), root.name))

    start = time.perf_counter()
    docs = workspace_service.discover_docs(extension, ignore)
    discovered = time.perf_counter()

    graph = ImportGraph(root, [root], docs).build()
    built = time.perf_counter()

    edges = sum(map(len, graph.imports.values()))
    malformed_output.write_text("".join(f"{path}\n" for path in graph.malformed))

    typer.echo(
        dedent(
            f"""\
            Discovered {len(docs)} document(s) in {discovered - start:.3f}s
            Built the import graph ({edges} import edge(s)) in {built - discovered:.3f}s
            Total: {built - start:.3f}s
            {len(graph.malformed)} document(s) failed to parse, see {malformed_output}
            """
        )
    )


if __name__ == "__main__":
    app()
