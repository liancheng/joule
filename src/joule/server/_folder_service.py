import asyncio as A
from functools import cached_property
from pathlib import Path

from lsprotocol import types as L

from joule.analysis.imports import ImportGraph
from joule.config import Config
from joule.workspace import FolderIndex


class FolderService:
    folder: L.WorkspaceFolder
    config: Config
    index: FolderIndex | None

    # File events that arrive before the index exists.
    _pending_events: list[L.FileEvent]

    def __init__(self, folder: L.WorkspaceFolder, config: Config):
        self.folder = folder
        self.config = config
        self.index = None
        self._pending_events = []

    @cached_property
    def opened_root(self) -> Path:
        """The unresolved absolute root path editors sent for this workspace folder,

        Symlinks are not resolved, so that Joule works with symlinked workspace folders.
        """
        return Path.from_uri(self.folder.uri).absolute()

    @cached_property
    def root(self) -> Path:
        """The resolved absolute root path of this workspace folder."""
        return self.opened_root.resolve()

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

                if (
                    path.is_relative_to(self.opened_root)
                    and self.opened_root != self.root
                ):
                    # Converts symlinked paths to their real paths, since source
                    # discovery and import resolution do not follow symplinks.
                    path = self.root.joinpath(path.relative_to(self.opened_root))

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
