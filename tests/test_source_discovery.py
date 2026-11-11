import asyncio as A
from pathlib import Path

import lsprotocol.types as L

from joule.analysis.imports import ImportGraph
from joule.analysis.sources import discover_sources
from joule.config import Config
from joule.server import FolderService
from joule.workspace import FolderIndex
from tests import FakeWorkspaceTestCase


class TestSourceDiscovery(FakeWorkspaceTestCase):
    def assertSourcesDiscovered(self, index: FolderIndex, *expected: str):
        __tracebackhide__ = True

        files = [
            path
            for path in self.root.rglob("*", recurse_symlinks=True)
            if not path.is_dir()
        ]

        obtained = {
            path.relative_to(self.root)
            for path in files
            if index.import_graph.is_source(path)
        }

        discovered = {
            path.relative_to(self.root)
            for path in discover_sources(self.source_config, self.root)
        }

        self.assertSetEqual(obtained, set(map(Path, expected)))
        self.assertSetEqual(obtained, discovered)

    def test_case_insensitive(self):
        index = self.index_workspace(
            self.file("F1.Jsonnet"),
            self.file("f2.JSONNET"),
            self.file("F3.jsonnet"),
        )

        self.assertSourcesDiscovered(
            index,
            "F1.Jsonnet",
            "f2.JSONNET",
            "F3.jsonnet",
        )

    def test_extension_with_dot(self):
        index = self.index_workspace(self.file("f.jsonnet.TEMPLATE"))
        self.assertSourcesDiscovered(index, "f.jsonnet.TEMPLATE")

    def test_data_files(self):
        index = self.index_workspace(
            self.file("f1.jsonnet"),
            self.file("f2.json"),
        )

        self.assertSourcesDiscovered(index, "f1.jsonnet")

    def test_nested_excluded_folders(self):
        with self.exclude("excluded/"):
            index = self.index_workspace(
                self.file("f.jsonnet"),
                self.file("excluded/f.jsonnet"),
                self.file("d/f.jsonnet"),
                self.file("d/excluded/f.jsonnet"),
            )

            self.assertSourcesDiscovered(
                index,
                "f.jsonnet",
                "d/f.jsonnet",
            )

    def test_hidden_files(self):
        index = self.index_workspace(
            self.file("f.jsonnet"),
            self.file(".f.jsonnet"),
            self.file(".hidden"),
        )

        self.assertSourcesDiscovered(index, "f.jsonnet")

    def test_nested_hidden_folders(self):
        index = self.index_workspace(
            self.file("f.jsonnet"),
            self.file(".hidden/f.jsonnet"),
            self.file("d/f.jsonnet"),
            self.file("d/.hidden/f.jsonnet"),
        )

        self.assertSourcesDiscovered(
            index,
            "f.jsonnet",
            "d/f.jsonnet",
        )

    def test_no_symlinked_files(self):
        index = self.index_workspace(
            self.file("d/f.jsonnet"),
            self.symlink("link.jsonnet", "d/f.jsonnet"),
        )

        self.assertSourcesDiscovered(index, "d/f.jsonnet")

    def test_no_symlinked_dirs(self):
        index = self.index_workspace(
            self.file("d1/f.jsonnet"),
            self.symlink("d2/d3", "d1"),
        )

        self.assertSourcesDiscovered(index, "d1/f.jsonnet")

    def test_file_events(self):
        self.provision(
            self.file(
                "f1.jsonnet",
                """\
                local a = import "f2.libsonnet";
                local b = import "data.json";
                [a, b]
                """,
            ),
        )

        index = self.index_workspace(self.file("f2.libsonnet", 'import "f1.jsonnet"'))
        index.on_file_created(self.root.joinpath("f2.libsonnet"))
        self.assertImportGraphInSync(index.import_graph)

        index = self.index_workspace(self.file("data.json", "{}"))
        index.on_file_created(self.root.joinpath("data.json"))
        self.assertImportGraphInSync(index.import_graph)

        index = self.index_workspace(self.file("f2.libsonnet", "{}"))
        index.on_file_changed(self.root.joinpath("f2.libsonnet"))
        self.assertImportGraphInSync(index.import_graph)

        # On macOS, editors can report a change as a creation.
        index = self.index_workspace(self.file("f2.libsonnet", 'import "f1.jsonnet"'))
        index.on_file_created(self.root.joinpath("f2.libsonnet"))
        self.assertImportGraphInSync(index.import_graph)

        self.delete("f2.libsonnet", "data.json")
        index.on_file_deleted(self.root.joinpath("f2.libsonnet"))
        index.on_file_deleted(self.root.joinpath("data.json"))
        self.assertImportGraphInSync(index.import_graph)

    def test_service_applies_queued_events(self):

        def uri(path: str) -> str:
            return self.root.joinpath(path).as_uri()

        self.provision(
            self.file("f1.jsonnet", 'import "f2.libsonnet"'),
            self.file("f2.libsonnet", "{}"),
        )

        folder = L.WorkspaceFolder(self.root.as_uri(), "workspace")
        service = FolderService(folder, Config(sources=self.source_config))

        # The events arrive before the index exists. The build also sees the
        # changes, and the events are applied again after the build.
        self.provision(self.file("f3.libsonnet", 'import "f1.jsonnet"'))
        service.on_file_event(
            L.FileEvent(uri("f3.libsonnet"), L.FileChangeType.Created)
        )
        self.delete("f2.libsonnet")
        service.on_file_event(
            L.FileEvent(uri("f2.libsonnet"), L.FileChangeType.Deleted)
        )

        self.assertFalse(service.ready)
        A.run(service.start())

        index = self.assertIsDefined(service.index)
        self.assertImportGraphInSync(index.import_graph)
        self.assertSetEqual(
            index.import_graph.imports_of(self.root.joinpath("f3.libsonnet")),
            {self.root.joinpath("f1.jsonnet")},
        )

    def test_service_resolves_symlinked_root(self):
        self.provision(
            self.file("real/f1.jsonnet", 'import "f2.libsonnet"'),
            self.file("real/f3.libsonnet", "{}"),
            self.symlink("link", "real"),
        )

        real = self.root.joinpath("real")
        link = self.root.joinpath("link")

        # A watcher on the symlinked folder reports event paths through the
        # symlink. The folder URI keeps the symlink too. Editors can also report
        # the real paths. Each way must update the index.
        for folder_uri, event_path in [
            (link.as_uri(), link.joinpath("f2.libsonnet")),
            (real.as_uri(), real.joinpath("f2.libsonnet")),
        ]:
            with self.subTest(folder_uri=folder_uri):
                folder = L.WorkspaceFolder(folder_uri, "workspace")
                service = FolderService(folder, Config(sources=self.source_config))
                A.run(service.start())

                self.provision(self.file("real/f2.libsonnet", "{}"))
                service.on_file_event(
                    L.FileEvent(event_path.as_uri(), L.FileChangeType.Created)
                )

                # A change through the symlink must reach the index. The index
                # only accepts real paths.
                self.provision(self.file("real/f2.libsonnet", 'import "f3.libsonnet"'))
                service.on_file_event(
                    L.FileEvent(event_path.as_uri(), L.FileChangeType.Changed)
                )

                index = service.index
                assert index is not None
                self.assertEqual(
                    index.import_graph, ImportGraph.build(real, self.source_config)
                )
                self.assertSetEqual(
                    index.import_graph.imports_of(real.joinpath("f2.libsonnet")),
                    {real.joinpath("f3.libsonnet")},
                )
