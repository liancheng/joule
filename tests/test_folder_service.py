import asyncio as A
from pathlib import Path

import lsprotocol.types as L

from joule.config import Config
from joule.server import FolderService
from tests import FakeWorkspaceTestCase


class TestFolderService(FakeWorkspaceTestCase):
    def folder_service(self, folder: str | Path) -> FolderService:
        uri = self.root.joinpath(folder).as_uri()
        workspace_folder = L.WorkspaceFolder(uri, "workspace")
        return FolderService(workspace_folder, Config(sources=self.source_config))

    def send(self, service: FolderService, type: L.FileChangeType, path: str):
        service.on_file_event(L.FileEvent(self.root.joinpath(path).as_uri(), type))

    def test_queued_events(self):
        self.provision(
            f1 := self.file("f1.jsonnet", 'import "f2.libsonnet"'),
            self.file("f2.libsonnet", "{}"),
        )

        service = self.folder_service(".")

        self.provision(f3 := self.file("f3.libsonnet", 'import "f1.jsonnet"'))
        self.send(service, L.FileChangeType.Created, "f3.libsonnet")
        self.delete("f2.libsonnet")
        self.send(service, L.FileChangeType.Deleted, "f2.libsonnet")

        # The build also sees the changes. Then the service applies the queued events
        # again.
        self.assertFalse(service.ready)
        A.run(service.start())

        index = self.assertIsDefined(service.index)
        self.assertImports(index, importer=f3, importees=[f1])
        self.assertImports(index, importer=f1, importees=[])
        self.assertImportGraphInSync(index.import_graph)

    def test_symlinked_root_event_through_symlink(self):
        self.provision(
            f1 := self.file("real/f1.jsonnet", "{}"),
            f2 := self.file("real/f2.libsonnet"),
            self.symlink("link", "real"),
        )

        service = self.folder_service("link")
        A.run(service.start())

        self.provision(self.file("real/f1.jsonnet", 'import "f2.libsonnet"'))
        self.send(service, L.FileChangeType.Changed, "link/f1.jsonnet")

        index = self.assertIsDefined(service.index)
        self.assertImports(index, importer=f1, importees=[f2])

        with self.workspace_root("real"):
            self.assertImportGraphInSync(index.import_graph)

    def test_symlinked_root_event_through_real_path(self):
        self.provision(
            f1 := self.file("real/f1.jsonnet", "{}"),
            f2 := self.file("real/f2.libsonnet"),
            self.symlink("link", "real"),
        )

        service = self.folder_service("link")
        A.run(service.start())

        self.provision(self.file("real/f1.jsonnet", 'import "f2.libsonnet"'))
        self.send(service, L.FileChangeType.Changed, "real/f1.jsonnet")

        index = self.assertIsDefined(service.index)
        self.assertImports(index, importer=f1, importees=[f2])

        with self.workspace_root("real"):
            self.assertImportGraphInSync(index.import_graph)
