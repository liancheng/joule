import shutil
import subprocess
from pathlib import Path

from joule.config import SourcesConfig

__all__ = [
    "discover_sources",
]


def discover_sources(root: Path, config: SourcesConfig) -> list[Path]:
    fd = shutil.which("fd") or shutil.which("fdfind")

    if fd is None:
        raise RuntimeError("`fd` not found in PATH")

    # Do not follow symlinks. Editors report only the real paths of files. Thus a
    # source under a symlinked directory never gets updates.
    command = [fd, "--type", "file", "--absolute-path"]

    for extension in config.extensions:
        command += ["--extension", extension]

    for pattern in config.exclude:
        command += ["--exclude", pattern]

    command += [".", root.absolute().as_posix()]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=True,
    )

    return [Path(line) for line in result.stdout.splitlines() if line]
