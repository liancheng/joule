import asyncio as A
from pathlib import Path

from lsprotocol import types as L

from joule.analysis.imports import ImportGraph
from joule.config import Config
from joule.syntax import trees as T
from joule.workspace import FolderIndex, resolve_document


class FolderService:
    folder: L.WorkspaceFolder
    config: Config
    root: Path
    index: FolderIndex | None

    # File events that arrive before the index exists.
    _pending_events: list[L.FileEvent]

    def __init__(self, folder: L.WorkspaceFolder, config: Config):
        self.folder = folder
        self.config = config
        self.root = Path.from_uri(folder.uri).absolute()
        self.index = None
        self._pending_events = []

    async def start(self) -> None:
        build = ImportGraph.build_in_parallel
        graph = await A.to_thread(build, self.root, self.config.sources)
        self.index = FolderIndex(graph)

        # The build can already see some of these changes. The events are idempotent,
        # so it is safe to apply them again.
        for event in self._pending_events:
            self.on_file_event(event)

        self._pending_events.clear()

    def on_file_event(self, event: L.FileEvent):
        match self.index:
            case None:
                self._pending_events.append(event)
            case index:
                path = Path.from_uri(event.uri)

                match event.type:
                    case L.FileChangeType.Created:
                        index.on_file_created(path)
                    case L.FileChangeType.Changed:
                        index.on_file_changed(path)
                    case L.FileChangeType.Deleted:
                        index.on_file_deleted(path)

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
