from itertools import tee
from pathlib import Path
from textwrap import dedent
from typing import Iterable

from tests import TempWorkspaceTestCase


class DocumentStoreTestCase(TempWorkspaceTestCase):
    def assertPathsEquals(
        self,
        obtained: Iterable[Path],
        dirs: Iterable[Path],
        files: Iterable[Path],
    ):
        i1, i2 = tee(obtained)
        obtained_dirs = filter(lambda path: path.is_dir(), i1)
        obtained_files = filter(lambda path: path.is_file(), i2)

        self.assertSequenceEqual(sorted(obtained_dirs), sorted(dirs))
        self.assertSequenceEqual(sorted(obtained_files), sorted(files))


class TestDocumentStoreScan(DocumentStoreTestCase):
    def test_scan(self):
        self.write_file("", self.to_uri(".git/config"))
        self.write_file("", self.to_uri("d2/__init__.py"))

        store = self.fake_document_store(
            [
                self.fake_document("1", sub_path="d1/f1.jsonnet"),
                self.fake_document("2", sub_path="d2/f2.jsonnet"),
            ],
            load=False,
        )

        self.assertPathsEquals(
            store.scan(self.workspace_root),
            dirs=[
                self.workspace_root,
                self.workspace_root.joinpath("d1"),
                self.workspace_root.joinpath("d2"),
            ],
            files=[
                self.workspace_root.joinpath("d1/f1.jsonnet"),
                self.workspace_root.joinpath("d2/f2.jsonnet"),
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

        self.assertSequenceEqual(
            sorted(store.trees.keys()),
            sorted(
                [
                    self.to_uri("f1.jsonnet"),
                    self.to_uri("f2.jsonnet"),
                    self.to_uri("f3.jsonnet"),
                    self.to_uri("f4.jsonnet"),
                    self.to_uri("f6.jsonnet"),
                    self.to_uri("vendor/f5.jsonnet"),
                ]
            ),
        )

        self.assertDictEqual(
            store.imports,
            {
                self.to_uri("f2.jsonnet"): {
                    self.to_uri("f1.jsonnet"),
                },
                self.to_uri("f3.jsonnet"): {
                    self.to_uri("f2.jsonnet"),
                },
                self.to_uri("f4.jsonnet"): {
                    self.to_uri("f1.jsonnet"),
                },
                self.to_uri("f6.jsonnet"): {
                    self.to_uri("f2.jsonnet"),
                    self.to_uri("f3.jsonnet"),
                    self.to_uri("vendor/f5.jsonnet"),
                },
            },
        )

        self.assertDictEqual(
            store.importedBy,
            {
                self.to_uri("f1.jsonnet"): {
                    self.to_uri("f2.jsonnet"),
                    self.to_uri("f4.jsonnet"),
                },
                self.to_uri("f2.jsonnet"): {
                    self.to_uri("f3.jsonnet"),
                    self.to_uri("f6.jsonnet"),
                },
                self.to_uri("f3.jsonnet"): {
                    self.to_uri("f6.jsonnet"),
                },
                self.to_uri("vendor/f5.jsonnet"): {
                    self.to_uri("f6.jsonnet"),
                },
            },
        )
