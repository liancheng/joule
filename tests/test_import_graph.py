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

    def test_simple_import(self):
        with self.jpaths("."):
            self.assertImports(
                index=self.index_workspace(
                    f1 := self.fake_document(
                        "f1.jsonnet",
                        """\
                        [
                            import "f2.libsonnet",
                            import "f3.libsonnet",
                        ]
                        """,
                    ),
                    f2 := self.fake_document("f2.libsonnet", "1"),
                    f3 := self.fake_document("f3.libsonnet", "2"),
                ),
                importer=f1,
                importees=[f2, f3],
            )

    def test_duplicate_imports(self):
        with self.jpaths("."):
            self.assertImports(
                index=self.index_workspace(
                    f1 := self.fake_document(
                        "f1.jsonnet",
                        """\
                        [
                            import "f2.libsonnet",
                            import "f2.libsonnet",
                        ]
                        """,
                    ),
                    f2 := self.fake_document("f2.libsonnet", "1"),
                ),
                importer=f1,
                importees=[f2],
            )

    def test_importer_dir_and_jpaths(self):
        with self.jpaths("vendor"):
            self.assertImports(
                index=self.index_workspace(
                    f1 := self.fake_document(
                        "app/f1.jsonnet",
                        """\
                        [
                            import "./f2.libsonnet",
                            import "sub/f3.libsonnet",
                        ]
                        """,
                    ),
                    f2 := self.fake_document("app/f2.libsonnet", "1"),
                    f3 := self.fake_document("vendor/sub/f3.libsonnet", "2"),
                ),
                importer=f1,
                importees=[f2, f3],
            )

    def test_non_source_importee(self):
        # Source discovery does not find `.json` files, but they are importees.
        self.assertImports(
            index=self.index_workspace(
                f := self.fake_document("f1.jsonnet", 'import "data.json"'),
                data := self.fake_document("data.json", "{}"),
            ),
            importer=f,
            importees=[data],
        )

    def test_unresolved_import(self):
        self.assertImports(
            index=self.index_workspace(
                f := self.fake_document(
                    "f1.jsonnet",
                    'import "missing.libsonnet"',
                ),
            ),
            importer=f,
            importees=[],
        )

    def test_importstr_and_importbin(self):
        self.provision(
            self.file("notes.txt", "notes"),
            self.file("blob.bin", "blob"),
        )

        self.assertImports(
            index=self.index_workspace(
                f := self.fake_document(
                    "f1.jsonnet",
                    """\
                    local text = importstr "notes.txt";
                    local blob = importbin "blob.bin";
                    [text, blob]
                    """,
                ),
            ),
            importer=f,
            importees=[],
        )

    def test_no_imports(self):
        self.assertImports(
            index=self.index_workspace(
                f := self.fake_document("app/f1.jsonnet", "{}"),
            ),
            importer=f,
            importees=[],
        )

    def test_source_with_syntax_error(self):
        self.assertImports(
            index=self.index_workspace(
                f1 := self.fake_document(
                    "f1.jsonnet",
                    """\
                    [
                        import "f2.libsonnet",
                        // The syntax error affects only this array element. Thus the import
                        // still parses, and the import graph records it.
                        { broken }
                    ]
                    """,
                ),
                f2 := self.fake_document("f2.libsonnet", "1"),
            ),
            importer=f1,
            importees=[f2],
        )

    def test_file_changed(self):
        index = self.index_workspace(
            f1 := self.fake_document("f1.jsonnet", 'import "f2.libsonnet"'),
            self.fake_document("f2.libsonnet", "1"),
            f3 := self.fake_document("f3.libsonnet", "2"),
        )

        self.provision(self.file("f1.jsonnet", 'import "f3.libsonnet"'))
        index.on_file_changed(f1.path)

        self.assertImports(index, importer=f1, importees=[f3])
        self.assertEqual(index.import_graph, self.build_import_graph())

    def test_file_changed_syntax_error(self):
        index = self.index_workspace(
            f1 := self.fake_document("f1.jsonnet", 'import "f2.libsonnet"'),
            f2 := self.fake_document("f2.libsonnet", "1"),
        )

        self.provision(self.file("f1.jsonnet", '[import "f2.libsonnet", {]'))
        index.on_file_changed(f1.path)

        self.assertImports(index, importer=f1, importees=[f2])
        self.assertEqual(index.import_graph, self.build_import_graph())

        self.provision(self.file("f1.jsonnet", "{}"))
        index.on_file_changed(f1.path)

        self.assertImports(index, importer=f1, importees=[])
        self.assertEqual(index.import_graph, self.build_import_graph())

    def test_file_created_resolves_import(self):
        f2 = self.fake_document(
            "f2.libsonnet",
            'import "f1.jsonnet"',
        )

        index = self.index_workspace(
            f1 := self.fake_document(
                "f1.jsonnet",
                'import "f2.libsonnet"',
            ),
        )

        self.provision(self.file("f2.libsonnet", f2.text))
        index.on_file_created(f2.path)

        self.assertImports(index, importer=f1, importees=[f2])
        self.assertImports(index, importer=f2, importees=[f1])
        self.assertEqual(index.import_graph, self.build_import_graph())

    def test_file_created_shadows_jpath(self):
        local = self.fake_document("app/lib.libsonnet", "2")

        with self.jpaths("vendor"):
            index = self.index_workspace(
                f1 := self.fake_document(
                    "app/f1.jsonnet",
                    'import "lib.libsonnet"',
                ),
                self.fake_document(
                    "vendor/lib.libsonnet",
                    "1",
                ),
            )

            self.provision(self.file("app/lib.libsonnet", local.text))
            index.on_file_created(local.path)

            self.assertImports(index, importer=f1, importees=[local])
            self.assertEqual(index.import_graph, self.build_import_graph())

    def test_file_created_with_same_file_name(self):
        lib_util = self.fake_document(
            "lib/util.libsonnet",
            "1",
        )

        index = self.index_workspace(
            f1 := self.fake_document(
                "a/f1.jsonnet",
                'import "util.libsonnet"',
            ),
            f2 := self.fake_document(
                "b/f2.jsonnet",
                'import "../lib/util.libsonnet"',
            ),
            f3 := self.fake_document(
                "c/f3.jsonnet",
                'import "util.jsonnet"',
            ),
        )

        self.provision(self.file("lib/util.libsonnet", lib_util.text))
        index.on_file_created(lib_util.path)

        self.assertImports(index, importer=f1, importees=[])
        self.assertImports(index, importer=f2, importees=[lib_util])
        self.assertImports(index, importer=f3, importees=[])
        self.assertEqual(index.import_graph, self.build_import_graph())

    def test_file_created_not_a_source(self):
        data = self.fake_document(
            "data.json",
            "{}",
        )

        index = self.index_workspace(
            f := self.fake_document(
                "f1.jsonnet",
                """\
                local data = import "data.json";
                local text = importstr "notes.txt";
                [data, text]
                """,
            ),
        )

        self.provision(self.file("data.json", data.text), self.file("notes.txt"))
        index.on_file_created(data.path)
        index.on_file_created(self.root.joinpath("notes.txt"))

        # Only `import` makes edges, also for files that are not sources.
        self.assertImports(index, importer=f, importees=[data])
        self.assertEqual(index.import_graph, self.build_import_graph())

    def test_file_deleted_falls_back_to_jpath(self):
        with self.jpaths("vendor"):
            index = self.index_workspace(
                f1 := self.fake_document(
                    "app/f1.jsonnet",
                    'import "lib.libsonnet"',
                ),
                local := self.fake_document(
                    "app/lib.libsonnet",
                    "1",
                ),
                vendored := self.fake_document(
                    "vendor/lib.libsonnet",
                    "2",
                ),
            )

            self.delete("app/lib.libsonnet")
            index.on_file_deleted(local.path)

            self.assertImports(index, importer=f1, importees=[vendored])
            self.assertEqual(index.import_graph, self.build_import_graph())

    def test_file_deleted_importee(self):
        index = self.index_workspace(
            f1 := self.fake_document(
                "f1.jsonnet",
                'import "./f2.libsonnet"',
            ),
            f2 := self.fake_document(
                "f2.libsonnet",
                "1",
            ),
        )

        self.delete("f2.libsonnet")
        index.on_file_deleted(f2.path)

        self.assertImports(index, importer=f1, importees=[])
        self.assertEqual(index.import_graph, self.build_import_graph())

        # The unresolved import resolves again when the file comes back.
        self.provision(self.file("f2.libsonnet", f2.text))
        index.on_file_created(f2.path)

        self.assertImports(index, importer=f1, importees=[f2])
        self.assertEqual(index.import_graph, self.build_import_graph())

    def test_file_deleted_importer(self):
        index = self.index_workspace(
            f1 := self.fake_document(
                "f1.jsonnet",
                '[import "f2.libsonnet", {]',
            ),
            self.fake_document(
                "f2.libsonnet",
                "1",
            ),
        )

        self.delete("f1.jsonnet")
        index.on_file_deleted(f1.path)

        self.assertImports(index, importer=f1, importees=[])
        self.assertEqual(index.import_graph, self.build_import_graph())

    def test_pretty(self):
        with self.jpaths("."):
            index = self.index_workspace(
                self.fake_document(
                    "lib/f2.libsonnet",
                    "1",
                ),
                self.fake_document(
                    "f1.jsonnet",
                    """\
                    local a = import "lib/f2.libsonnet";
                    local b = import "missing.libsonnet";
                    [a, b, {]
                    """,
                ),
            )

            self.assertEqual(
                index.import_graph.pretty,
                dedent(
                    """\
                    imports:
                      f1.jsonnet: lib/f2.libsonnet
                    imported by:
                      lib/f2.libsonnet: f1.jsonnet
                    raw importees:
                      f1.jsonnet: 'lib/f2.libsonnet'
                      f1.jsonnet: 'missing.libsonnet'
                    file names:
                      'f2.libsonnet': f1.jsonnet
                      'missing.libsonnet': f1.jsonnet
                    """
                ),
            )

            self.assertEqual(
                repr(index.import_graph),
                f"ImportGraph(root={str(self.root)!r}, 1 edges)",
            )
