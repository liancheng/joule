import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Iterable

from joule import ast as A
from joule.config import JouleConfig
from joule.model import DocumentStore
from tests.dsl.util import side_by_side

from .dsl import FakeDocument

unittest.TestCase.maxDiff = None
unittest.TestCase.longMessage = False


class ASTTestCase(unittest.TestCase):
    def assertAstEqual(self, tree_or_source: A.AST | str, expected: A.AST | str):
        match tree_or_source, expected:
            case A.AST() as obtained, str() as expected:
                lhs = obtained.pretty_tree
                rhs = expected.strip()
                self.assertMultiLineEqual(lhs, rhs, side_by_side(lhs, rhs))
            case A.AST() as obtained, A.AST() as expected:
                self.assertAstEqual(obtained, expected.pretty_tree)
            case str() as source, A.AST() as expected:
                self.assertAstEqual(FakeDocument(source).body, expected.pretty_tree)
            case str() as source, str():
                self.assertAstEqual(FakeDocument(source).body, expected)


class TempWorkspaceTestCase(unittest.TestCase):
    temp_dir: TemporaryDirectory
    workspace_root: Path
    workspace_uri: A.URI

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory(ignore_cleanup_errors=True)
        self.workspace_root = Path(self.temp_dir.name)
        self.workspace_uri = self.workspace_root.as_uri()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def fake_document(self, source: str, sub_path: str = "f.jsonnet") -> FakeDocument:
        return FakeDocument(source, uri=self.to_uri(sub_path))

    def write_file(self, content: str, uri: A.URI):
        path = Path.from_uri(uri)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def fake_workspace(
        self,
        docs: list[FakeDocument] | FakeDocument | dict[str, str],
        config: JouleConfig = JouleConfig(),
        load: bool = True,
    ) -> DocumentStore:
        match docs:
            case FakeDocument():
                docs = [docs]
            case dict():
                docs = [
                    FakeDocument(source, self.to_uri(sub_path))
                    for sub_path, source in docs.items()
                ]
            case _:
                pass

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

    def to_uri(self, sub_path: str) -> A.URI:
        return self.to_path(sub_path).as_uri()

    def to_uris(self, sub_paths: Iterable[str]) -> Iterable[A.URI]:
        return (self.to_uri(sub_path) for sub_path in sub_paths)
