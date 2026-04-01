from textwrap import dedent

from joule.ast import URI
from joule.config import JouleConfig
from joule.model import DocumentStore
from tests import TempWorkspaceTestCase


class DocumentStoreTestCase(TempWorkspaceTestCase):
    def _build_import_graph(self, graph: dict[str, set[str]]) -> dict[URI, set[URI]]:
        return {self.to_uri(k): set(self.to_uris(v)) for k, v in graph.items()}

    def assertScannedPathsEqual(self, store: DocumentStore, sub_paths: list[str]):
        self.assertSequenceEqual(
            sorted(store.scan()),
            sorted(self.to_paths(sub_paths)),
        )

    def assertIndexedDocumentsEqual(self, store: DocumentStore, sub_paths: list[str]):
        self.assertSequenceEqual(
            sorted(store.trees),
            sorted(self.to_uris(sub_paths)),
        )

    def assertLibraryPathsEqual(self, store: DocumentStore, sub_paths: list[str]):
        self.assertSequenceEqual(
            sorted(store.library_paths),
            sorted(self.to_paths(sub_paths)),
        )

    def assertImportsEqual(self, store: DocumentStore, imports: dict[str, set[str]]):
        self.assertDictEqual(store.imports, self._build_import_graph(imports))

    def assertImportedByEqual(
        self,
        store: DocumentStore,
        imported_by: dict[str, set[str]],
    ):
        self.assertDictEqual(store.imported_by, self._build_import_graph(imported_by))

    def assertRecursiveImportersEqual(
        self,
        store: DocumentStore,
        importee: str,
        importers: list[str],
    ):
        self.assertSequenceEqual(
            sorted(store.recursive_importers(self.to_uri(importee))),
            sorted(self.to_uris(importers)),
        )


class TestDocumentStoreScan(DocumentStoreTestCase):
    def test_exclude(self):
        self.write_file("", self.to_uri(".DS_Store"))

        store = self.fake_document_store(
            [self.fake_document("0", sub_path="d/f.jsonnet")],
            config=JouleConfig(exclude=["**/.DS_Store"]),
            load=False,
        )

        self.assertScannedPathsEqual(
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

        self.assertScannedPathsEqual(
            store,
            ["src/f.jsonnet"],
        )

    def test_library_paths(self):
        store = self.fake_document_store(
            [
                self.fake_document("0", sub_path="vendor/f.jsonnet"),
                self.fake_document("0", sub_path="d/vendor/f.jsonnet"),
            ],
            config=JouleConfig(library_paths=["**/vendor"]),
            load=False,
        )

        self.assertScannedPathsEqual(
            store,
            [
                "d/vendor",
                "d/vendor/f.jsonnet",
                "vendor",
                "vendor/f.jsonnet",
            ],
        )


class TestDocumentStoreLoadWorkspace(DocumentStoreTestCase):
    store: DocumentStore

    def setUp(self) -> None:
        super().setUp()
        self.store = self.fake_document_store(
            [
                self.fake_document(
                    "1",
                    sub_path="f1.jsonnet",
                ),
                self.fake_document(
                    'import "f1.jsonnet"',
                    sub_path="f2.jsonnet",
                ),
                self.fake_document(
                    'import "f2.jsonnet"',
                    sub_path="f3.jsonnet",
                ),
                self.fake_document(
                    'import "f1.jsonnet"',
                    sub_path="f4.jsonnet",
                ),
                self.fake_document(
                    "2",
                    sub_path="vendor/f5.jsonnet",
                ),
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
            ],
            load=False,
        )

    def test_load_workspace(self):
        self.store.load_workspace()

        self.assertIndexedDocumentsEqual(
            self.store,
            [
                "f1.jsonnet",
                "f2.jsonnet",
                "f3.jsonnet",
                "f4.jsonnet",
                "f6.jsonnet",
                "vendor/f5.jsonnet",
            ],
        )

        self.assertLibraryPathsEqual(
            self.store,
            ["vendor"],
        )

        self.assertImportsEqual(
            self.store,
            {
                "f2.jsonnet": {"f1.jsonnet"},
                "f3.jsonnet": {"f2.jsonnet"},
                "f4.jsonnet": {"f1.jsonnet"},
                "f6.jsonnet": {"f2.jsonnet", "f3.jsonnet", "vendor/f5.jsonnet"},
            },
        )

        self.assertImportedByEqual(
            self.store,
            {
                "f1.jsonnet": {"f2.jsonnet", "f4.jsonnet"},
                "f2.jsonnet": {"f3.jsonnet", "f6.jsonnet"},
                "f3.jsonnet": {"f6.jsonnet"},
                "vendor/f5.jsonnet": {"f6.jsonnet"},
            },
        )

        self.assertRecursiveImportersEqual(
            self.store,
            importee="f1.jsonnet",
            importers=[
                "f2.jsonnet",
                "f3.jsonnet",
                "f4.jsonnet",
                "f6.jsonnet",
            ],
        )

    def test_delete(self):
        self.store.load_workspace()
        self.store.delete(self.to_uri("f2.jsonnet"))

        self.assertIndexedDocumentsEqual(
            self.store,
            [
                "f1.jsonnet",
                "f3.jsonnet",
                "f4.jsonnet",
                "f6.jsonnet",
                "vendor/f5.jsonnet",
            ],
        )

        self.assertLibraryPathsEqual(
            self.store,
            ["vendor"],
        )

        self.assertImportsEqual(
            self.store,
            {
                "f3.jsonnet": set(),
                "f4.jsonnet": {"f1.jsonnet"},
                "f6.jsonnet": {"f3.jsonnet", "vendor/f5.jsonnet"},
            },
        )

        self.assertImportedByEqual(
            self.store,
            {
                "f1.jsonnet": {"f4.jsonnet"},
                "f3.jsonnet": {"f6.jsonnet"},
                "vendor/f5.jsonnet": {"f6.jsonnet"},
            },
        )

        self.assertRecursiveImportersEqual(
            self.store,
            importee="f1.jsonnet",
            importers=["f4.jsonnet"],
        )
