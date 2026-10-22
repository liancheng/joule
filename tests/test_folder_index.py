from joule.workspace import resolve_document
from tests import FakeWorkspaceTestCase, File


class TestFolderIndex(FakeWorkspaceTestCase):
    def test_malformed_document(self):
        with self.layout(File(path := "bad.jsonnet", "}")):
            uri = self.root.joinpath(path).as_uri()
            self.assertIsNone(resolve_document(uri))
