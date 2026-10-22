from joule.workspace import FolderIndex
from tests import FakeWorkspaceTestCase
from tests.dsl import FakeDocument


class TestImportGraph(FakeWorkspaceTestCase):
    def assertImports(
        self,
        index: FolderIndex,
        importer: FakeDocument,
        *importees: FakeDocument,
    ):
        __tracebackhide__ = True

        graph = index.import_graph

        self.assertSetEqual(
            {self.rel_path(path) for path in graph.imports.get(importer.path, set())},
            {self.rel_path(importee) for importee in importees},
        )

        for importee in importees:
            self.assertSetEqual(
                {
                    self.rel_path(path)
                    for path in graph.imported_by.get(importee.path, set())
                },
                {self.rel_path(importer)},
            )

    def assertMalformed(self, index: FolderIndex, *docs: FakeDocument):
        __tracebackhide__ = True
        self.assertCountEqual(
            [self.rel_path(path) for path in index.import_graph.malformed],
            [self.rel_path(doc) for doc in docs],
        )

    def assertImportees(
        self,
        index: FolderIndex,
        importer: FakeDocument,
        *raw_importees: str,
    ):
        __tracebackhide__ = True
        self.assertSetEqual(
            index.import_graph.importees.get(importer.path, set()),
            set(raw_importees),
        )

    def assertBasenameImported(
        self,
        index: FolderIndex,
        basename: str,
        *importers: FakeDocument,
    ):
        __tracebackhide__ = True
        graph = index.import_graph
        self.assertSetEqual(
            {
                self.rel_path(path)
                for path in graph.basename_imported_by.get(basename, set())
            },
            {self.rel_path(importer) for importer in importers},
        )

    def test_simple_import(self):
        f1 = self.fake_document(
            """\
            local a = import "f2.libsonnet";
            local b = import "f3.libsonnet";
            [a, b]
            """,
            path="f1.jsonnet",
        )

        f2 = self.fake_document(
            "1",
            path="f2.libsonnet",
        )

        f3 = self.fake_document(
            "2",
            path="f3.libsonnet",
        )

        with (
            self.jpaths("."),
            self.workspace(f1, f2, f3) as index,
        ):
            self.assertImports(index, f1, f2, f3)
            self.assertBasenameImported(index, "f2.libsonnet", f1)
            self.assertBasenameImported(index, "f3.libsonnet", f1)

    def test_duplicate_imports(self):
        f1 = self.fake_document(
            """\
            local a = import "f2.libsonnet";
            local b = import "f2.libsonnet";
            [a, b]
            """,
            path="f1.jsonnet",
        )

        f2 = self.fake_document(
            "1",
            path="f2.libsonnet",
        )

        with (
            self.jpaths("."),
            self.workspace(f1, f2) as index,
        ):
            self.assertImports(index, f1, f2)
            self.assertBasenameImported(index, "f2.libsonnet", f1)

    def test_importer_dir_and_jpaths(self):
        f1 = self.fake_document(
            """\
            local a = import "./f2.libsonnet";
            local b = import "sub/f3.libsonnet";
            [a, b]
            """,
            path="app/f1.jsonnet",
        )

        f2 = self.fake_document(
            "1",
            path="app/f2.libsonnet",
        )

        f3 = self.fake_document(
            "2",
            path="vendor/sub/f3.libsonnet",
        )

        with (
            self.jpaths("vendor"),
            self.workspace(f1, f2, f3) as index,
        ):
            self.assertImports(index, f1, f2, f3)
            self.assertImportees(index, f1, "./f2.libsonnet", "sub/f3.libsonnet")
            self.assertBasenameImported(index, "f2.libsonnet", f1)
            self.assertBasenameImported(index, "f3.libsonnet", f1)

    def test_non_document_importee(self):
        f = self.fake_document(
            'import "data.json"',
            path="f1.jsonnet",
        )

        data = self.fake_document(
            "{}",
            path="data.json",
        )

        with self.workspace(f, data) as index:
            # Document discovery does not find `.json` files, but they are importees.
            self.assertImports(index, f, data)
            self.assertBasenameImported(index, "data.json", f)

    def test_unresolved_import(self):
        f = self.fake_document(
            'import "missing.libsonnet"',
            path="f1.jsonnet",
        )

        with self.workspace(f) as index:
            self.assertImports(index, f)
            # Unresolved importees are kept. A new file can make them resolve.
            self.assertImportees(index, f, "missing.libsonnet")
            self.assertBasenameImported(index, "missing.libsonnet", f)

    def test_importstr_and_importbin(self):
        f = self.fake_document(
            """\
            local text = importstr "notes.txt";
            local blob = importbin "blob.bin";
            [text, blob]
            """,
            path="f1.jsonnet",
        )

        with (
            self.layout(
                self.file("notes.txt", "notes"),
                self.file("blob.bin", "blob"),
            ),
            self.workspace(f) as index,
        ):
            self.assertImports(index, f)
            self.assertImportees(index, f)
            self.assertBasenameImported(index, "notes.txt")
            self.assertBasenameImported(index, "blob.bin")

    def test_no_imports(self):
        f = self.fake_document(
            "{}",
            path="app/f1.jsonnet",
        )

        with self.workspace(f) as index:
            self.assertImports(index, f)
            self.assertImportees(index, f)

    def test_malformed_document(self):
        f1 = self.fake_document(
            """\
            local a = import "f2.libsonnet";
            [
                a,
                // The malformed node affects only this array element. Thus the import
                // still parses, and the import graph records it.
                { malformed }
            ]
            """,
            path="f1.jsonnet",
        )

        f2 = self.fake_document(
            "1",
            path="f2.libsonnet",
        )

        with self.workspace(f1, f2) as index:
            self.assertMalformed(index, f1)
            self.assertImports(index, f1, f2)
            self.assertBasenameImported(index, "f2.libsonnet", f1)

    def test_importers_of_same_file_name(self):
        f1 = self.fake_document(
            'import "util.libsonnet"',
            path="a/f1.jsonnet",
        )

        f2 = self.fake_document(
            'import "../lib/util.libsonnet"',
            path="b/f2.jsonnet",
        )

        f3 = self.fake_document(
            'import "util.jsonnet"',
            path="c/f3.jsonnet",
        )

        with self.workspace(f1, f2, f3) as index:
            self.assertBasenameImported(index, "util.libsonnet", f1, f2)
            self.assertBasenameImported(index, "util.jsonnet", f3)
