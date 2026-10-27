from textwrap import dedent

from joule.workspace import FolderIndex
from tests import FakeWorkspaceTestCase
from tests.dsl import FakeDocument


class TestImportGraph(FakeWorkspaceTestCase):
    def assertImports(
        self,
        index: FolderIndex,
        *,
        importer: FakeDocument,
        importees: list[FakeDocument],
    ):
        __tracebackhide__ = True

        g = index.import_graph

        self.assertSetEqual(
            g.imports_of(importer.path),
            {importee.path for importee in importees},
        )

        for importee in importees:
            self.assertIn(importer.path, g.importers_of(importee.path))

    def assertMalformed(self, index: FolderIndex, docs: list[FakeDocument]):
        __tracebackhide__ = True
        self.assertSetEqual(index.import_graph.malformed, {doc.path for doc in docs})

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
            self.assertImports(index, importer=f1, importees=[f2, f3])

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
            self.assertImports(index, importer=f1, importees=[f2])

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
            self.assertImports(index, importer=f1, importees=[f2, f3])

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
            self.assertImports(index, importer=f, importees=[data])

    def test_unresolved_import(self):
        f = self.fake_document(
            'import "missing.libsonnet"',
            path="f1.jsonnet",
        )

        with self.workspace(f) as index:
            self.assertImports(index, importer=f, importees=[])

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
            self.assertImports(index, importer=f, importees=[])

    def test_no_imports(self):
        f = self.fake_document(
            "{}",
            path="app/f1.jsonnet",
        )

        with self.workspace(f) as index:
            self.assertImports(index, importer=f, importees=[])

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
            self.assertMalformed(index, [f1])
            self.assertImports(index, importer=f1, importees=[f2])

    def test_file_changed(self):
        f1 = self.fake_document(
            'import "f2.libsonnet"',
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

        with self.workspace(f1, f2, f3) as index:
            self.provision(self.file("f1.jsonnet", 'import "f3.libsonnet"'))
            index.import_graph.file_changed(f1.path)

            self.assertImports(index, importer=f1, importees=[f3])
            self.assertEqual(index.import_graph, self.build_import_graph())

    def test_file_changed_malformed(self):
        f1 = self.fake_document(
            'import "f2.libsonnet"',
            path="f1.jsonnet",
        )

        f2 = self.fake_document(
            "1",
            path="f2.libsonnet",
        )

        with self.workspace(f1, f2) as index:
            self.provision(self.file("f1.jsonnet", '[import "f2.libsonnet", {]'))
            index.import_graph.file_changed(f1.path)

            self.assertMalformed(index, [f1])
            self.assertImports(index, importer=f1, importees=[f2])
            self.assertEqual(index.import_graph, self.build_import_graph())

            self.provision(self.file("f1.jsonnet", "{}"))
            index.import_graph.file_changed(f1.path)

            self.assertMalformed(index, [])
            self.assertImports(index, importer=f1, importees=[])
            self.assertEqual(index.import_graph, self.build_import_graph())

    def test_file_created_resolves_import(self):
        f1 = self.fake_document(
            'import "f2.libsonnet"',
            path="f1.jsonnet",
        )

        f2 = self.fake_document(
            'import "f1.jsonnet"',
            path="f2.libsonnet",
        )

        with self.workspace(f1) as index:
            self.provision(self.file("f2.libsonnet", f2.text))
            index.import_graph.file_created(f2.path)
            index.import_graph.file_changed(f2.path)

            self.assertImports(index, importer=f1, importees=[f2])
            self.assertImports(index, importer=f2, importees=[f1])
            self.assertEqual(index.import_graph, self.build_import_graph())

    def test_file_created_shadows_jpath(self):
        f1 = self.fake_document(
            'import "lib.libsonnet"',
            path="app/f1.jsonnet",
        )

        vendored = self.fake_document(
            "1",
            path="vendor/lib.libsonnet",
        )

        local = self.fake_document(
            "2",
            path="app/lib.libsonnet",
        )

        with (
            self.jpaths("vendor"),
            self.workspace(f1, vendored) as index,
        ):
            self.provision(self.file("app/lib.libsonnet", local.text))
            index.import_graph.file_created(local.path)
            index.import_graph.file_changed(local.path)

            self.assertImports(index, importer=f1, importees=[local])
            self.assertEqual(index.import_graph, self.build_import_graph())

    def test_file_created_with_same_file_name(self):
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

        lib_util = self.fake_document(
            "1",
            path="lib/util.libsonnet",
        )

        with self.workspace(f1, f2, f3) as index:
            self.provision(self.file("lib/util.libsonnet", lib_util.text))
            index.import_graph.file_created(lib_util.path)
            index.import_graph.file_changed(lib_util.path)

            self.assertImports(index, importer=f1, importees=[])
            self.assertImports(index, importer=f2, importees=[lib_util])
            self.assertImports(index, importer=f3, importees=[])
            self.assertEqual(index.import_graph, self.build_import_graph())

    def test_file_created_not_a_document(self):
        f = self.fake_document(
            """\
            local data = import "data.json";
            local text = importstr "notes.txt";
            [data, text]
            """,
            path="f1.jsonnet",
        )

        data = self.fake_document(
            "{}",
            path="data.json",
        )

        with self.workspace(f) as index:
            self.provision(self.file("data.json", data.text), self.file("notes.txt"))
            index.import_graph.file_created(data.path)
            index.import_graph.file_created(self.root.joinpath("notes.txt"))

            # Only `import` makes edges, also for files that are not documents.
            self.assertImports(index, importer=f, importees=[data])
            self.assertEqual(index.import_graph, self.build_import_graph())

    def test_file_deleted_falls_back_to_jpath(self):
        f1 = self.fake_document(
            'import "lib.libsonnet"',
            path="app/f1.jsonnet",
        )

        local = self.fake_document(
            "1",
            path="app/lib.libsonnet",
        )

        vendored = self.fake_document(
            "2",
            path="vendor/lib.libsonnet",
        )

        with (
            self.jpaths("vendor"),
            self.workspace(f1, local, vendored) as index,
        ):
            self.delete("app/lib.libsonnet")
            index.import_graph.file_deleted(local.path)

            self.assertImports(index, importer=f1, importees=[vendored])
            self.assertEqual(index.import_graph, self.build_import_graph())

    def test_file_deleted_importee(self):
        f1 = self.fake_document(
            'import "./f2.libsonnet"',
            path="f1.jsonnet",
        )

        f2 = self.fake_document(
            "1",
            path="f2.libsonnet",
        )

        with self.workspace(f1, f2) as index:
            self.delete("f2.libsonnet")
            index.import_graph.file_deleted(f2.path)

            self.assertImports(index, importer=f1, importees=[])
            self.assertEqual(index.import_graph, self.build_import_graph())

            # The unresolved import resolves again when the file comes back.
            self.provision(self.file("f2.libsonnet", f2.text))
            index.import_graph.file_created(f2.path)
            index.import_graph.file_changed(f2.path)

            self.assertImports(index, importer=f1, importees=[f2])
            self.assertEqual(index.import_graph, self.build_import_graph())

    def test_file_deleted_importer(self):
        f1 = self.fake_document(
            '[import "f2.libsonnet", {]',
            path="f1.jsonnet",
        )

        f2 = self.fake_document(
            "1",
            path="f2.libsonnet",
        )

        with self.workspace(f1, f2) as index:
            self.delete("f1.jsonnet")
            index.import_graph.file_deleted(f1.path)

            self.assertImports(index, importer=f1, importees=[])
            self.assertMalformed(index, [])
            self.assertEqual(index.import_graph, self.build_import_graph())

    def test_pretty(self):
        f1 = self.fake_document(
            """\
            local a = import "lib/f2.libsonnet";
            local b = import "missing.libsonnet";
            [a, b, {]
            """,
            path="f1.jsonnet",
        )

        f2 = self.fake_document(
            "1",
            path="lib/f2.libsonnet",
        )

        with (
            self.jpaths("."),
            self.workspace(f1, f2) as index,
        ):
            self.assertEqual(
                index.import_graph.pretty,
                dedent(
                    """\
                    imports:
                      f1.jsonnet: lib/f2.libsonnet
                    imported by:
                      lib/f2.libsonnet: f1.jsonnet
                    importees:
                      f1.jsonnet: 'lib/f2.libsonnet'
                      f1.jsonnet: 'missing.libsonnet'
                    file names:
                      'f2.libsonnet': f1.jsonnet
                      'missing.libsonnet': f1.jsonnet
                    malformed:
                      f1.jsonnet
                    """
                ),
            )

            self.assertEqual(
                repr(index.import_graph),
                f"ImportGraph(root={str(self.root)!r}, 1 edges, 1 malformed)",
            )
