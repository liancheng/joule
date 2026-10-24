from pathlib import Path

from joule.workspace import discover_docs, resolve_document
from tests import FakeWorkspaceTestCase


class TestFolderIndex(FakeWorkspaceTestCase):
    def test_malformed_document(self):
        with self.layout(self.file(path := "bad.jsonnet", "}")):
            uri = self.root.joinpath(path).as_uri()
            self.assertIsNone(resolve_document(uri))

    def test_no_symlinks(self):
        with self.layout(
            self.file("gen/lib.libsonnet"),
            self.symlink("vendor/lib", "gen"),
            self.symlink("alias.libsonnet", "gen/lib.libsonnet"),
        ):
            docs = discover_docs(self.root, ["libsonnet"], None)
            self.assertEqual(
                [self.rel_path(doc) for doc in docs],
                [Path("gen/lib.libsonnet")],
            )
