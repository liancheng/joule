from pathlib import Path

from joule.analysis.sources import discover_sources
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
