import asyncio as A
from pathlib import Path
from typing import Any
from unittest import mock

import lsprotocol.types as L

from joule.analysis.imports import BuildObserver, ImportGraph
from joule.config import Config, SourcesConfig
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


class FakeProgressSender:
    # Each call is (method, token, value). The value of `create_async` is `None`.
    calls: list[tuple[str, str, object]]

    def __init__(self):
        self.calls = []

    async def create_async(self, token: str) -> object:
        self.calls.append(("create", token, None))
        return None

    def begin(self, token: str, value: L.WorkDoneProgressBegin) -> None:
        self.calls.append(("begin", token, value))

    def report(self, token: str, value: L.WorkDoneProgressReport) -> None:
        self.calls.append(("report", token, value))

    def end(self, token: str, value: L.WorkDoneProgressEnd) -> None:
        self.calls.append(("end", token, value))

    def kinds(self, token: str) -> list[str]:
        return [kind for kind, t, _ in self.calls if t == token]

    def values(self, token: str, kind: str) -> list[Any]:
        return [value for k, t, value in self.calls if t == token and k == kind]


def fail_after_discovery(
    root: Path,
    config: SourcesConfig,
    *,
    observer: BuildObserver,
) -> ImportGraph:
    observer.on_discovery_done(1)
    raise RuntimeError("The build failed.")


def fail_before_discovery_done(
    root: Path,
    config: SourcesConfig,
    *,
    observer: BuildObserver,
) -> ImportGraph:
    raise RuntimeError("The build failed.")


class TestFolderServiceProgress(FakeWorkspaceTestCase):
    def progress_service(self, sender: FakeProgressSender) -> FolderService:
        folder = L.WorkspaceFolder(self.root.as_uri(), "workspace")
        return FolderService(folder, Config(sources=self.source_config), sender)

    def tokens(self) -> tuple[str, str]:
        uri = self.root.as_uri()
        return f"joule/discovery/{uri}", f"joule/import-graph/{uri}"

    def test_discovery_begins_without_percentage(self):
        self.provision(self.file("f1.jsonnet"))

        sender = FakeProgressSender()
        A.run(self.progress_service(sender).start())

        discovery, _ = self.tokens()
        self.assertEqual(sender.kinds(discovery), ["create", "begin", "end"])

        [begin] = sender.values(discovery, "begin")
        self.assertIsNone(begin.percentage)
        self.assertEqual(
            begin.title,
            "Discovering Jsonnet sources: workspace",
        )

    def test_import_graph_reports_each_percentage_once(self):
        self.provision(*(self.file(f"f{i}.jsonnet") for i in range(1, 5)))

        sender = FakeProgressSender()
        A.run(self.progress_service(sender).start())

        _, graph = self.tokens()
        self.assertEqual(
            sender.kinds(graph),
            ["create", "begin", "report", "report", "report", "report", "end"],
        )

        [begin] = sender.values(graph, "begin")
        self.assertEqual(begin.percentage, 0)

        reports = sender.values(graph, "report")
        self.assertEqual(
            [r.percentage for r in reports],
            [25, 50, 75, 100],
        )
        self.assertEqual(
            [r.message for r in reports],
            ["1/4 files", "2/4 files", "3/4 files", "4/4 files"],
        )

    def test_import_graph_sends_at_most_101_reports(self):
        self.provision(*(self.file(f"f{i}.jsonnet") for i in range(200)))

        sender = FakeProgressSender()
        A.run(self.progress_service(sender).start())

        _, graph = self.tokens()
        percentages = [r.percentage for r in sender.values(graph, "report")]

        self.assertLessEqual(len(percentages), 101)
        self.assertEqual(percentages, sorted(set(percentages)))
        self.assertEqual(percentages[-1], 100)

    def test_no_sources_ends_import_graph_at_once(self):
        sender = FakeProgressSender()
        A.run(self.progress_service(sender).start())

        discovery, graph = self.tokens()
        self.assertEqual(sender.kinds(discovery), ["create", "begin", "end"])
        self.assertEqual(sender.kinds(graph), ["create", "begin", "end"])

        [end] = sender.values(graph, "end")
        self.assertEqual(end.message, "0 files")

    def test_build_raises_after_discovery(self):
        self.provision(self.file("f1.jsonnet"))

        sender = FakeProgressSender()
        service = self.progress_service(sender)

        with (
            mock.patch.object(
                ImportGraph,
                "build_in_parallel",
                new=fail_after_discovery,
            ),
            self.assertRaises(RuntimeError),
        ):
            A.run(service.start())

        discovery, graph = self.tokens()
        self.assertEqual(sender.kinds(discovery), ["create", "begin", "end"])
        self.assertEqual(sender.kinds(graph), ["create", "begin", "end"])

    def test_build_raises_before_discovery_done(self):
        sender = FakeProgressSender()
        service = self.progress_service(sender)

        with (
            mock.patch.object(
                ImportGraph,
                "build_in_parallel",
                new=fail_before_discovery_done,
            ),
            self.assertRaises(RuntimeError),
        ):
            A.run(service.start())

        discovery, graph = self.tokens()
        self.assertEqual(sender.kinds(discovery), ["create", "begin", "end"])
        self.assertEqual(sender.kinds(graph), ["create", "end"])
