import asyncio as A
import shutil
import subprocess
from pathlib import Path

from lsprotocol import types as L

from joule.analysis.imports import ImportGraph
from joule.config import Config


class FolderIndex:
    folder: L.WorkspaceFolder
    config: Config
    import_graph: ImportGraph | None

    def __init__(self, folder: L.WorkspaceFolder, config: Config):
        self.folder: L.WorkspaceFolder = folder
        self.config = config
        self.import_graph = None

    async def start(self) -> None:
        root = Path.from_uri(self.folder.uri).absolute()
        jpaths = [Path(path) for path in self.config.jpaths]
        docs = await A.to_thread(
            self.discover_docs,
            self.config.extensions,
            self.config.exclude,
        )
        graph = ImportGraph(root, jpaths, docs)
        self.import_graph = await A.to_thread(graph.build)

    @property
    def ready(self) -> bool:
        return self.import_graph is not None

    def discover_docs(
        self,
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

        command += [".", Path.from_uri(self.folder.uri).absolute().as_posix()]

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
        )

        return [Path(line) for line in result.stdout.splitlines() if line]
