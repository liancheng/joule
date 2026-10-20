import shutil
import subprocess
from pathlib import Path

from joule.analysis.imports import ImportGraph
from joule.analysis.scopes import resolve
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


def resolve_document(uri: str) -> T.Document | None:
    return head_or_none(resolve(doc) for doc in maybe(T.parse_document(uri)))


class FolderIndex:
    import_graph: ImportGraph

    def __init__(self, import_graph: ImportGraph):
        self.import_graph = import_graph

    # TODO: Caches resolved AST trees and invalidates on updates.
    def resolve_document(self, uri: str) -> T.Document | None:
        return resolve_document(uri)
