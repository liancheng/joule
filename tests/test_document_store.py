from pathlib import Path
from textwrap import dedent

from joule.ast import URI
from joule.config import JouleConfig
from joule.model import DocumentStore
from tests import TempWorkspaceTestCase


class DocumentStoreTestCase(TempWorkspaceTestCase):
    def _build_import_graph(self, graph: dict[str, set[str]]) -> dict[URI, set[URI]]:
        return {
            self.to_uri(k): set(map(lambda i: self.to_uri(i), v))
            for k, v in graph.items()
        }

    def checkScan(self, store: DocumentStore, sub_paths: list[str]):
        self.assertSequenceEqual(
            sorted(store.scan()),
            sorted(Path.from_uri(self.to_uri(sub_path)) for sub_path in sub_paths),
        )

    def checkTrees(self, store: DocumentStore, sub_paths: list[str]):
        self.assertSequenceEqual(
            sorted(store.trees),
            sorted(self.to_uri(sub_path) for sub_path in sub_paths),
        )

    def checkLibraryPaths(self, store: DocumentStore, sub_paths: list[str]):
        self.assertSequenceEqual(
            sorted(store.library_paths),
            sorted(Path.from_uri(self.to_uri(sub_path)) for sub_path in sub_paths),
        )

    def checkImports(self, store: DocumentStore, imports: dict[str, set[str]]):
        self.assertDictEqual(store.imports, self._build_import_graph(imports))

    def checkImportedBy(self, store: DocumentStore, imported_by: dict[str, set[str]]):
        self.assertDictEqual(store.imported_by, self._build_import_graph(imported_by))


class TestDocumentStoreScan(DocumentStoreTestCase):
    def test_exclude(self):
        self.write_file("", self.to_uri(".DS_Store"))

        store = self.fake_document_store(
            [self.fake_document("0", sub_path="d/f.jsonnet")],
            config=JouleConfig(exclude=["**/.DS_Store"]),
            load=False,
        )

        self.checkScan(
            store,
            ["d/f.jsonnet"],
        )

    def test_include(self):
        store = self.fake_document_store(
            [
                self.fake_document("0", "src/f.jsonnet"),
                self.fake_document("0", "test/f.jsonnet"),
            ],
            config=JouleConfig(include=["**/src/**"]),
            load=False,
        )

        self.checkScan(
            store,
            ["src/f.jsonnet"],
        )

    def test_library_paths(self):
        store = self.fake_document_store(
            [
                self.fake_document("0", sub_path="d1/f1.jsonnet"),
                self.fake_document("0", sub_path="vendor/d2/f2.jsonnet"),
                self.fake_document("0", sub_path="d3/vendor/d4/f3.jsonnet"),
            ],
            config=JouleConfig(library_paths=["**/vendor"]),
            load=False,
        )

        self.checkScan(
            store,
            [
                "vendor",
                "d3/vendor",
                "d1/f1.jsonnet",
                "vendor/d2/f2.jsonnet",
                "d3/vendor/d4/f3.jsonnet",
            ],
        )


class TestDocumentStoreLoadWorkspace(DocumentStoreTestCase):
    def test_load_workspace(self):
        store = self.fake_document_store(
            [
                self.fake_document("1", sub_path="f1.jsonnet"),
                self.fake_document('import "f1.jsonnet"', sub_path="f2.jsonnet"),
                self.fake_document('import "f2.jsonnet"', sub_path="f3.jsonnet"),
                self.fake_document('import "f1.jsonnet"', sub_path="f4.jsonnet"),
                self.fake_document("2", sub_path="vendor/f5.jsonnet"),
                self.fake_document(
                    dedent(
                        """\
                        local v1 = import 'f2.jsonnet';
                        local v2 = import 'f3.jsonnet';
                        local v3 = import 'f5.jsonnet';
                        v1 + v2 + v3
                        """
                    ),
                    sub_path="f6.jsonnet",
                ),
            ]
        )

        self.checkTrees(
            store,
            [
                "f1.jsonnet",
                "f2.jsonnet",
                "f3.jsonnet",
                "f4.jsonnet",
                "f6.jsonnet",
                "vendor/f5.jsonnet",
            ],
        )

        self.checkLibraryPaths(
            store,
            ["vendor"],
        )

        self.checkImports(
            store,
            {
                "f2.jsonnet": {"f1.jsonnet"},
                "f3.jsonnet": {"f2.jsonnet"},
                "f4.jsonnet": {"f1.jsonnet"},
                "f6.jsonnet": {"f2.jsonnet", "f3.jsonnet", "vendor/f5.jsonnet"},
            },
        )

        self.checkImportedBy(
            store,
            {
                "f1.jsonnet": {"f2.jsonnet", "f4.jsonnet"},
                "f2.jsonnet": {"f3.jsonnet", "f6.jsonnet"},
                "f3.jsonnet": {"f6.jsonnet"},
                "vendor/f5.jsonnet": {"f6.jsonnet"},
            },
        )
