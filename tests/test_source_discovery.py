import asyncio as A
from pathlib import Path

import lsprotocol.types as L

from joule.analysis.imports import is_source
from joule.analysis.sources import discover_sources
from joule.config import Config
from joule.server import FolderService
from tests import FakeWorkspaceTestCase


class TestSourceDiscovery(FakeWorkspaceTestCase):
    def assertSourcesDiscovered(self, *expected: str):
        __tracebackhide__ = True

        files = [
            path
            for path in self.root.rglob("*", recurse_symlinks=True)
            if path.is_file()
        ]

        obtained = {
            path.relative_to(self.root)
            for path in files
            if is_source(self.source_config, self.root, path)
        }

        discovered = {
            path.relative_to(self.root)
            for path in discover_sources(self.source_config, self.root)
        }

        self.assertSetEqual(obtained, set(map(Path, expected)))
        self.assertSetEqual(obtained, discovered)

    def test_case_insensitive(self):
        self.provision(
            self.file("F1.Jsonnet"),
            self.file("f2.JSONNET"),
            self.file("F3.jsonnet"),
        )

        self.assertSourcesDiscovered(
            "F1.Jsonnet",
            "f2.JSONNET",
            "F3.jsonnet",
        )

    def test_extension_with_dot(self):
        self.provision(self.file("f.jsonnet.TEMPLATE"))
        self.assertSourcesDiscovered("f.jsonnet.TEMPLATE")

    def test_data_files(self):
        self.provision(
            self.file("f1.jsonnet"),
            self.file("f2.json"),
        )

        self.assertSourcesDiscovered("f1.jsonnet")

    def test_nested_excluded_folders(self):
        self.provision(
            self.file("f.jsonnet"),
            self.file("excluded/f.jsonnet"),
            self.file("d/f.jsonnet"),
            self.file("d/excluded/f.jsonnet"),
        )

        with self.exclude("excluded/"):
            self.assertSourcesDiscovered(
                ("f.jsonnet"),
                ("d/f.jsonnet"),
            )

    def test_hidden_files(self):
        self.provision(
            self.file("f.jsonnet"),
            self.file(".f.jsonnet"),
            self.file(".hidden"),
        )

        self.assertSourcesDiscovered("f.jsonnet")

    def test_nested_hidden_folders(self):
        self.provision(
            self.file("f.jsonnet"),
            self.file(".hidden/f.jsonnet"),
            self.file("d/f.jsonnet"),
            self.file("d/.hidden/f.jsonnet"),
        )

        self.assertSourcesDiscovered(
            ("f.jsonnet"),
            ("d/f.jsonnet"),
        )

    def test_no_symlinks(self):
        self.provision(
            self.file("d/f.jsonnet"),
            self.symlink("link.jsonnet", "d/f.jsonnet"),
        )

        self.assertSourcesDiscovered("d/f.jsonnet")

    def test_file_events(self):
        index = self.index_workspace(
            self.file(
                "f1.jsonnet",
                """\
                local a = import "f2.libsonnet";
                local b = import "data.json";
                [a, b]
                """,
            ),
        )

        self.provision(self.file("f2.libsonnet", 'import "f1.jsonnet"'))
        index.on_file_created(self.root.joinpath("f2.libsonnet"))
        self.assertImportGraphInSync(index.import_graph)

        self.provision(self.file("data.json", "{}"))
        index.on_file_created(self.root.joinpath("data.json"))
        self.assertImportGraphInSync(index.import_graph)

        self.provision(self.file("f2.libsonnet", "{}"))
        index.on_file_changed(self.root.joinpath("f2.libsonnet"))
        self.assertImportGraphInSync(index.import_graph)

        # On macOS, editors can report a change as a creation.
        self.provision(self.file("f2.libsonnet", 'import "f1.jsonnet"'))
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

        index = service.index
        assert index is not None
        self.assertImportGraphInSync(index.import_graph)
        self.assertSetEqual(
            index.import_graph.imports_of(self.root.joinpath("f3.libsonnet")),
            {self.root.joinpath("f1.jsonnet")},
        )
