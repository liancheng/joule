import time
from pathlib import Path
from textwrap import dedent
from typing import Annotated

import typer
from typer import Typer

from joule.analysis.imports import ImportGraph
from joule.server import server
from joule.workspace import discover_docs

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

    start = time.perf_counter()
    docs = discover_docs(root, extension, exclude)
    discovered = time.perf_counter()

    graph = ImportGraph.build_in_parallel(root, [root], docs)
    built = time.perf_counter()

    edges = sum(1 for _ in graph.edges())
    malformed_output.write_text(
        "".join(f"{path}\n" for path in sorted(graph.malformed))
    )

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
