import time
from pathlib import Path
from textwrap import dedent
from typing import Annotated

import typer
from typer import Typer

from joule.analysis.imports import ImportGraph
from joule.analysis.sources import discover_sources
from joule.config import SourcesConfig
from joule.server import server

app = Typer(
    no_args_is_help=True,
    rich_markup_mode="markdown",
)

DEFAULT_EXTENSIONS = ["jsonnet", "libsonnet", "jsonnet.TEMPLATE"]


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
    exclude: Annotated[
        list[str] | None,
        typer.Option(
            "--exclude",
            "-x",
            help="Glob of files or folders to ignore. Repeat to ignore several.",
        ),
    ] = None,
):
    """Benchmark discovering Jsonnet files and building the import graph."""
    root = root.absolute()

    config = SourcesConfig(
        jpaths=[root],
        extensions=extension,
        exclude=[] if exclude is None else exclude,
    )

    start = time.perf_counter()
    sources = discover_sources(root, config)
    discovered = time.perf_counter()

    # The build runs the discovery again.
    graph = ImportGraph.build_in_parallel(root, config)
    built = time.perf_counter()
    edges = len(graph)

    typer.echo(
        dedent(
            f"""\
            Discovered {len(sources)} source(s) in {discovered - start:.3f}s
            Built the import graph ({edges} import edge(s)), including the discovery, in {built - discovered:.3f}s
            """
        )
    )


if __name__ == "__main__":
    app()
