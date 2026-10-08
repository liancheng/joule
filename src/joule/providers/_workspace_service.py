import asyncio as A
import shutil
import subprocess
from pathlib import Path

from lsprotocol import types as L

from joule.analysis.imports import ImportGraph


class WorkspaceService:
    folder: L.WorkspaceFolder
    import_graph: ImportGraph | None

    def __init__(self, folder: L.WorkspaceFolder):
        self.folder: L.WorkspaceFolder = folder
        self.import_graph = None

    async def start(self) -> None:
        # TODO: Wire `extensions` and `ignore` through LSP configuration.
        exts = ["jsonnet", "libsonnet", "jsonnet.TEMPLATE"]
        docs = await A.to_thread(self.discover_docs, exts, [])
        root = Path.from_uri(self.folder.uri).absolute()
        graph = ImportGraph(root, [root], docs)
        self.import_graph = await A.to_thread(graph.build)

    @property
    def ready(self) -> bool:
        return self.import_graph is not None

    def discover_docs(self, extensions: list[str], ignore: list[str]) -> list[Path]:
        fd = shutil.which("fd") or shutil.which("fdfind")

        if fd is None:
            raise RuntimeError("`fd` not found in PATH")

        command = [fd, "--type", "file", "--follow", "--absolute-path"]

        for extension in extensions:
            command += ["--extension", extension]

        for pattern in ignore:
            command += ["--exclude", pattern]

        command += [".", Path.from_uri(self.folder.uri).absolute().as_posix()]

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
        )

        return [Path(line) for line in result.stdout.splitlines() if line]
