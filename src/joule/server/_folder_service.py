import asyncio as A
from pathlib import Path

from lsprotocol import types as L

from joule.analysis.imports import ParallelImportGraphBuilder
from joule.config import Config
from joule.workspace import FolderIndex, discover_docs


class FolderService:
    folder: L.WorkspaceFolder
    config: Config
    index: FolderIndex

    def __init__(self, folder: L.WorkspaceFolder, config: Config):
        self.folder = folder
        self.config = config
        self.index = FolderIndex(
            root=Path.from_uri(folder.uri).absolute(),
            jpaths=[Path(path) for path in config.jpaths],
        )

    async def start(self) -> None:
        docs = await A.to_thread(
            discover_docs,
            self.index.root,
            self.config.extensions,
            self.config.exclude,
        )

        builder = ParallelImportGraphBuilder(self.index.root, self.index.jpaths)
        self.index.import_graph = await A.to_thread(builder.build, docs)

    @property
    def ready(self) -> bool:
        return self.index.import_graph is not None
