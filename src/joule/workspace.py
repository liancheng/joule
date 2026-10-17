import asyncio as A
import shutil
import subprocess
from pathlib import Path

from lsprotocol import types as L

from joule.analysis.imports import ImportGraph, ImportGraphBuilder
from joule.analysis.scopes import resolve
from joule.config import Config
from joule.maybe import head_or_none, maybe
from joule.syntax import trees as T


def discover_docs(
    root: Path,
    extensions: list[str],
    exclude: list[str] | None,
) -> list[Path]:
    fd = shutil.which("fd") or shutil.which("fdfind")

    if fd is None:
        raise RuntimeError("`fd` not found in PATH")

    command = [fd, "--type", "file", "--follow", "--absolute-path"]

    for extension in extensions:
        command += ["--extension", extension]

    if exclude is not None:
        for pattern in exclude:
            command += ["--exclude", pattern]

    command += [".", root.absolute().as_posix()]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=True,
    )

    return [Path(line) for line in result.stdout.splitlines() if line]


class FolderIndex:
    folder: L.WorkspaceFolder
    config: Config
    import_graph: ImportGraph | None

    def __init__(self, folder: L.WorkspaceFolder, config: Config):
        self.folder: L.WorkspaceFolder = folder
        self.config = config
        self.import_graph = None

    async def start(self) -> None:
        builder = ImportGraphBuilder(
            root=Path.from_uri(self.folder.uri).absolute(),
            jpaths=[Path(path) for path in self.config.jpaths],
        )

        docs = await A.to_thread(
            discover_docs,
            Path.from_uri(self.folder.uri),
            self.config.extensions,
            self.config.exclude,
        )

        self.import_graph = await A.to_thread(builder.build, docs)

    @property
    def ready(self) -> bool:
        return self.import_graph is not None

    # TODO: Caches resolved AST trees and invalidates on updates.
    def resolve_document(self, uri: str) -> T.Document | None:
        return head_or_none(resolve(doc) for doc in maybe(T.parse_document(uri)))
