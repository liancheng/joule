import shutil
import subprocess
from pathlib import Path

from lsprotocol import types as L

from joule.imports import ImportGraph


class WorkspaceService:
    folder: L.WorkspaceFolder
    import_graph: ImportGraph | None

    def __init__(self, folder: L.WorkspaceFolder):
        self.folder: L.WorkspaceFolder = folder
        self.import_graph = None

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
