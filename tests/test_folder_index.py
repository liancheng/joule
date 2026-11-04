import asyncio as A
from pathlib import Path

import lsprotocol.types as L

from joule.analysis.imports import is_source
from joule.analysis.sources import discover_sources
from joule.config import Config, SourcesConfig
from joule.server import FolderService
from joule.workspace import analyze_document
from tests import FakeWorkspaceTestCase


class TestFolderIndex(FakeWorkspaceTestCase):
    def test_malformed_source(self):
        with self.layout(self.file(path := "bad.jsonnet", "}")):
            uri = self.root.joinpath(path).as_uri()
            self.assertIsNone(analyze_document(uri))

    def test_no_symlinks(self):
        with self.layout(
            self.file("gen/lib.libsonnet"),
            self.symlink("vendor/lib", "gen"),
            self.symlink("alias.libsonnet", "gen/lib.libsonnet"),
        ):
            self.assertEqual(
                discover_sources(self.root, SourcesConfig(extensions=["libsonnet"])),
                [self.root.joinpath("gen/lib.libsonnet")],
            )

    def test_is_source_matches_discovery(self):
        config = SourcesConfig(exclude=["experimental/", ".*/", ".*"])

        with self.layout(
            self.file("a/x.jsonnet"),
            self.file("a/Y.jsonnet"),
            self.file("a/lib.libsonnet"),
            self.file("a/t.jsonnet.TEMPLATE"),
            self.file("a/data.json"),
            self.file("a/.hidden.jsonnet"),
            self.file(".hidden/h.jsonnet"),
            self.file("experimental/e.jsonnet"),
            self.file("b/experimental/e.jsonnet"),
            self.symlink("a/link.jsonnet", "a/x.jsonnet"),
        ):
            files = [path for path in self.root.rglob("*") if not path.is_dir()]

            obtained = {
                path.relative_to(self.root)
                for path in files
                if is_source(config, self.root, path)
            }

            discovered = {
                path.relative_to(self.root)
                for path in discover_sources(self.root, config)
            }

            self.assertSetEqual(obtained, discovered)
            self.assertSetEqual(
                obtained,
                {
                    Path("a/x.jsonnet"),
                    Path("a/Y.jsonnet"),
                    Path("a/lib.libsonnet"),
                    Path("a/t.jsonnet.TEMPLATE"),
                },
            )

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
            index.on_file_created(self.root / "f2.libsonnet")
            self.assertEqual(index.import_graph, self.build_import_graph())

            self.provision(self.file("data.json", "{}"))
            index.on_file_created(self.root / "data.json")
            self.assertEqual(index.import_graph, self.build_import_graph())

            self.provision(self.file("f2.libsonnet", "{}"))
            index.on_file_changed(self.root / "f2.libsonnet")
            self.assertEqual(index.import_graph, self.build_import_graph())

            # On macOS, editors can report a change as a creation.
            self.provision(self.file("f2.libsonnet", 'import "f1.jsonnet"'))
            index.on_file_created(self.root / "f2.libsonnet")
            self.assertEqual(index.import_graph, self.build_import_graph())

            self.delete("f2.libsonnet", "data.json")
            index.on_file_deleted(self.root / "f2.libsonnet")
            index.on_file_deleted(self.root / "data.json")
            self.assertEqual(index.import_graph, self.build_import_graph())

    def test_service_applies_queued_events(self):
        with self.layout(
            self.file("f1.jsonnet", 'import "f2.libsonnet"'),
            self.file("f2.libsonnet", "{}"),
        ):
            folder = L.WorkspaceFolder(self.root.as_uri(), "workspace")
            service = FolderService(folder, Config(sources=self.current_config))

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
            self.assertEqual(index.import_graph, self.build_import_graph())
            self.assertSetEqual(
                index.import_graph.imports_of(self.root / "f3.libsonnet"),
                {self.root / "f1.jsonnet"},
            )

    def uri(self, path: str) -> str:
        return self.root.joinpath(path).as_uri()
