from itertools import tee
from pathlib import Path
from typing import Iterable

from tests import TempWorkspaceTestCase


class TestDocumentStore(TempWorkspaceTestCase):
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

    def test_scan(self):
        store = self.fake_document_store(
            [
                self.fake_document("1", sub_path="d1/f1.jsonnet"),
                self.fake_document("2", sub_path="d2/f2.jsonnet"),
            ]
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
