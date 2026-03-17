from pyfakefs.fake_filesystem_unittest import TestCase

from joule.ast import URI
from joule.model import DocumentLoader

from .dsl import FakeDocument, fake_workspace


class FakeWorkspaceTestCase(TestCase):
    def setUp(self) -> None:
        self.setUpPyfakefs()

    def workspace(
        self,
        docs: FakeDocument | list[FakeDocument],
        root_uri: URI | None = None,
    ) -> DocumentLoader:
        return fake_workspace(self.fs, docs, root_uri)
