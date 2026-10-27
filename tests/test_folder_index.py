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
            self.assertEqual(
                discover_docs(self.root, ["libsonnet"], None),
                [self.root.joinpath("gen/lib.libsonnet")],
            )
