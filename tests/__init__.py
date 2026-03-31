import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pyfakefs.fake_filesystem_unittest import TestCase

from joule.ast import URI
from joule.config import JouleConfig
from joule.model import DocumentLoader, DocumentStore

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


def fake_document_store(
    docs: list[FakeDocument] | FakeDocument,
    workspace_uri: URI | None = None,
    config: JouleConfig = JouleConfig(),
):
    if isinstance(docs, FakeDocument):
        docs = [docs]

    match docs, workspace_uri:
        case [doc], None:
            workspace_uri = Path.from_uri(doc.uri).parent.as_uri()
        case _, None:
            raise ValueError("Mutiple documents provided. Missing workspace root URI.")
        case _:
            pass

    for doc in docs:
        doc_path = Path.from_uri(doc.uri)
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        doc_path.write_text(doc.source)

    store = DocumentStore(config, workspace_uri)
    store.load_workspace()

    return store


class TempWorkspaceTestCase(unittest.TestCase):
    temp_dir: TemporaryDirectory
    workspace_root: Path
    workspace_uri: URI

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory(ignore_cleanup_errors=True)
        self.workspace_root = Path(self.temp_dir.name)
        self.workspace_uri = self.workspace_root.as_uri()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def fake_document(self, source: str, sub_path: str = "f.jsonnet") -> FakeDocument:
        return FakeDocument(source, uri=self.workspace_root.joinpath(sub_path).as_uri())

    def fake_document_store(
        self,
        docs: list[FakeDocument] | FakeDocument,
        config: JouleConfig = JouleConfig(),
    ) -> DocumentStore:
        return fake_document_store(docs, self.workspace_uri, config)
