import asyncio as A
from pathlib import Path

from lsprotocol import types as L

from joule.analysis.imports import ImportGraph
from joule.config import Config
from joule.syntax import trees as T
from joule.workspace import FolderIndex, discover_docs, resolve_document


class FolderService:
    folder: L.WorkspaceFolder
    config: Config
    root: Path
    jpaths: list[Path]
    index: FolderIndex | None

    def __init__(self, folder: L.WorkspaceFolder, config: Config):
        self.folder = folder
        self.config = config
        self.index = None

    async def start(self) -> None:
        root = Path.from_uri(self.folder.uri).absolute()
        jpaths = [Path(path) for path in self.config.jpaths]

        docs = await A.to_thread(
            discover_docs,
            root,
            self.config.extensions,
            self.config.exclude,
        )

        build = ImportGraph.build_in_parallel
        self.index = FolderIndex(await A.to_thread(build, root, jpaths, docs))

    @property
    def ready(self) -> bool:
        return self.index is not None

    def resolve_document(self, uri: str) -> T.Document | None:
        # Single-document features do not need the import graph. Thus they do not
        # wait for the discovery and the build.
        return (
            resolve_document(uri)
            if self.index is None
            else self.index.resolve_document(uri)
        )
