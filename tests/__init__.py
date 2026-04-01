import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Iterable

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


class TempWorkspaceTestCase(unittest.TestCase):
    temp_dir: TemporaryDirectory
    workspace_root: Path
    workspace_uri: URI

    def __init__(self, methodName: str = "runTest") -> None:
        super().__init__(methodName)
        self.maxDiff = None

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory(ignore_cleanup_errors=True)
        self.workspace_root = Path(self.temp_dir.name)
        self.workspace_uri = self.workspace_root.as_uri()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def fake_document(self, source: str, sub_path: str = "f.jsonnet") -> FakeDocument:
        return FakeDocument(source, uri=self.to_uri(sub_path))

    def write_file(self, content: str, uri: URI):
        path = Path.from_uri(uri)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def fake_document_store(
        self,
        docs: list[FakeDocument] | FakeDocument,
        config: JouleConfig = JouleConfig(),
        load: bool = True,
    ) -> DocumentStore:
        for doc in [docs] if isinstance(docs, FakeDocument) else docs:
            self.write_file(doc.source, doc.uri)

        store = DocumentStore(config, self.workspace_uri)
        if load:
            store.load_workspace()
        return store

    def to_path(self, sub_path: str) -> Path:
        return self.workspace_root.joinpath(sub_path).resolve()

    def to_paths(self, sub_paths: Iterable[str]) -> Iterable[Path]:
        return (self.to_path(sub_path) for sub_path in sub_paths)

    def to_uri(self, sub_path: str) -> URI:
        return self.to_path(sub_path).as_uri()

    def to_uris(self, sub_paths: Iterable[str]) -> Iterable[URI]:
        return (self.to_uri(sub_path) for sub_path in sub_paths)
