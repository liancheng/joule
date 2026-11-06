import asyncio as A
from pathlib import Path

import lsprotocol.types as L

from joule.analysis.imports import ImportGraph, is_source
from joule.analysis.sources import discover_sources
from joule.config import Config
from joule.server import FolderService
from tests import FakeWorkspaceTestCase


class TestSourceDiscovery(FakeWorkspaceTestCase):
    def assertImportGraphInSync(self, graph: ImportGraph):
        __tracebackhide__ = True
        self.assertEqual(graph, self.build_import_graph())

    def assertSourcesDiscovered(self, *expected: Path):
        __tracebackhide__ = True

        files = [path for path in self.root.rglob("*") if not path.is_dir()]

        obtained = {
            path.relative_to(self.root)
            for path in files
            if is_source(self.source_config, self.root, path)
        }

        discovered = {
            path.relative_to(self.root)
            for path in discover_sources(self.source_config, self.root)
        }

        self.assertSetEqual(obtained, set(expected))
        self.assertSetEqual(obtained, discovered)

    def test_nested_excluded_folders(self):
        self.provision(
            self.file("f.jsonnet"),
            self.file("excluded/f.jsonnet"),
            self.file("d/f.jsonnet"),
            self.file("d/excluded/f.jsonnet"),
        )

        with self.exclude("excluded/"):
            self.assertSourcesDiscovered(
                Path("f.jsonnet"),
                Path("d/f.jsonnet"),
            )

    def test_hidden_files(self):
        self.provision(
            self.file("f.jsonnet"),
            self.file(".f.jsonnet"),
            self.file(".hidden"),
        )

        self.assertSourcesDiscovered(Path("f.jsonnet"))

    def test_nested_hidden_folders(self):
        self.provision(
            self.file("f.jsonnet"),
            self.file(".hidden/f.jsonnet"),
            self.file("d/f.jsonnet"),
            self.file("d/.hidden/f.jsonnet"),
        )

        self.assertSourcesDiscovered(
            Path("f.jsonnet"),
            Path("d/f.jsonnet"),
        )

    def test_no_symlinks(self):
        self.provision(
            self.file("f.jsonnet"),
            self.symlink("link.jsonnet", "f.jsonnet"),
        )

        self.assertSourcesDiscovered(Path("f.jsonnet"))

    def test_file_events(self):
        f1 = self.fake_document(
            """\
            local a = import "f2.libsonnet";
            local b = import "data.json";
            [a, b]
            """,
            path="f1.jsonnet",
        )

        with self.workspace(f1) as index:
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
            index.on_file_deleted(self.root / "f2.libsonnet")
            index.on_file_deleted(self.root / "data.json")
            self.assertImportGraphInSync(index.import_graph)

    def test_service_applies_queued_events(self):
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
            L.FileEvent(self.uri("f3.libsonnet"), L.FileChangeType.Created)
        )
        self.delete("f2.libsonnet")
        service.on_file_event(
            L.FileEvent(self.uri("f2.libsonnet"), L.FileChangeType.Deleted)
        )

        self.assertFalse(service.ready)
        A.run(service.start())

        index = service.index
        assert index is not None
        self.assertImportGraphInSync(index.import_graph)
        self.assertSetEqual(
            index.import_graph.imports_of(self.root / "f3.libsonnet"),
            {self.root / "f1.jsonnet"},
        )

    def uri(self, path: str) -> str:
        return self.root.joinpath(path).as_uri()
