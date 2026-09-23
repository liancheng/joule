from pathlib import Path

from lsprotocol import types as L
from lsprotocol.types import WorkspaceFolder


class LanguageService:
    def __init__(self, folder: L.WorkspaceFolder):
        self.folder: WorkspaceFolder = folder
        self.imports: dict[Path, set[Path]] = {}
        self.imported_by: dict[Path, set[Path]] = {}
