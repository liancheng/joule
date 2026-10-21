from joule.analysis.imports import ImportGraphBuilder, ParallelImportGraphBuilder
from joule.workspace import FolderIndex
from tests import FakeWorkspaceTestCase, File
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

        obtained_importees = graph.imports.get(importer.path, set())
        obtained = {path.relative_to(self.root) for path in obtained_importees}
        expected = {importee.path.relative_to(self.root) for importee in importees}
        self.assertSetEqual(obtained, expected)

        for importee in importees:
            obtained_importers = graph.imported_by.get(importee.path, set())
            obtained = {path.relative_to(self.root) for path in obtained_importers}
            expected = {importer.path.relative_to(self.root)}
            self.assertSetEqual(obtained, expected)

    def assertMalformed(self, index: FolderIndex, *docs: FakeDocument):
        __tracebackhide__ = True
        self.assertCountEqual(
            [path.relative_to(self.root) for path in index.import_graph.malformed],
            [doc.path.relative_to(self.root) for doc in docs],
        )

    def test_simple_import(self):
        f1 = self.fake_document(
            """\
            local a = import "lib/f2.libsonnet";
            local b = import "lib/f3.libsonnet";
            [a, b]
            """,
            path="app/f1.jsonnet",
        )

        f2 = self.fake_document(
            "1",
            path="lib/f2.libsonnet",
        )

        f3 = self.fake_document(
            "2",
            path="lib/f3.libsonnet",
        )

        with (
            self.jpaths("."),
            self.fake_workspace(f1, f2, f3) as index,
        ):
            self.assertImports(index, f1, f2, f3)

    def test_duplicate_imports(self):
        f1 = self.fake_document(
            """\
            local a = import "lib/f2.libsonnet";
            local b = import "lib/f2.libsonnet";
            [a, b]
            """,
            path="app/f1.jsonnet",
        )

        f2 = self.fake_document(
            "1",
            path="lib/f2.libsonnet",
        )

        with (
            self.jpaths("."),
            self.fake_workspace(f1, f2) as index,
        ):
            self.assertImports(index, f1, f2)

    def test_importer_dir_and_jpaths(self):
        f1 = self.fake_document(
            """\
            local a = import "f2.libsonnet";
            local b = import "f3.libsonnet";
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
            path="vendor/f3.libsonnet",
        )

        with (
            self.jpaths("vendor"),
            self.fake_workspace(f1, f2, f3) as index,
        ):
            self.assertImports(index, f1, f2, f3)

    def test_non_document_importee(self):
        f1 = self.fake_document(
            'import "data.json"',
            path="app/f1.jsonnet",
        )

        # Discovery does not find `.json` files, but they are import targets.
        data = self.fake_document(
            "{}",
            path="app/data.json",
        )

        with self.fake_workspace(f1, data) as index:
            self.assertImports(index, f1, data)

    def test_unresolved_import(self):
        f1 = self.fake_document(
            'import "missing.libsonnet"',
            path="app/f1.jsonnet",
        )

        with self.fake_workspace(f1) as index:
            self.assertImports(index, f1)

    def test_importstr_and_importbin(self):
        f1 = self.fake_document(
            """\
            local text = importstr "notes.txt";
            local blob = importbin "blob.bin";
            [text, blob]
            """,
            path="app/f1.jsonnet",
        )

        with (
            self.layout(
                File("app/notes.txt", "notes"),
                File("app/blob.bin", "blob"),
            ),
            self.fake_workspace(f1) as index,
        ):
            self.assertImports(index, f1)

    def test_no_imports(self):
        f1 = self.fake_document(
            "{}",
            path="app/f1.jsonnet",
        )

        with self.fake_workspace(f1) as index:
            self.assertImports(index, f1)

    def test_malformed_document(self):
        f1 = self.fake_document(
            'local x = import "f2.libsonnet"; [x, {1}]',
            path="app/f1.jsonnet",
        )

        f2 = self.fake_document(
            "1",
            path="app/f2.libsonnet",
        )

        with self.fake_workspace(f1, f2) as index:
            self.assertMalformed(index, f1)
            self.assertImports(index, f1)

    def test_deleted_document(self):
        # Discovery found `f1`, but somebody deleted it before the build.
        f1 = self.fake_document(
            'import "f2.libsonnet"',
            path="app/f1.jsonnet",
        )

        graph = ImportGraphBuilder(self.root, []).build([f1.path])
        index = FolderIndex(graph)

        self.assertMalformed(index, f1)
        self.assertImports(index, f1)

    def test_parallel_build(self):
        f1 = self.fake_document(
            """\
            local a = import "f2.libsonnet";
            local b = import "lib/f3.libsonnet";
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
            path="lib/f3.libsonnet",
        )

        f4 = self.fake_document(
            'local x = import "f2.libsonnet"; {',
            path="app/f4.jsonnet",
        )

        with (
            self.jpaths("."),
            self.fake_workspace(f1, f2, f3, f4) as index,
        ):
            docs = [doc.path for doc in (f1, f2, f3, f4)]
            jpaths = self.current_config.jpaths
            builder = ParallelImportGraphBuilder(self.root, jpaths, batch_size=1)
            graph = builder.build(docs)

            self.assertEqual(graph.imports, index.import_graph.imports)
            self.assertEqual(graph.imported_by, index.import_graph.imported_by)
            self.assertCountEqual(graph.malformed, index.import_graph.malformed)
