import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import cast, override

import ocdiff

from joule.analysis.imports import ImportGraph
from joule.config import SourcesConfig
from joule.syntax.trees import Tree
from joule.workspace import FolderIndex
from tests.dsl import DirEntry, FakeDocument, FileEntry, FsEntry, SymLinkEntry


class TreeTestCase(unittest.TestCase):
    @override
    def assertEqual(self, first, second, msg=None):
        # Handle `Tree`s here, not with `addTypeEqualityFunc`. `unittest` uses a type
        # equality function only if both arguments have exactly the same type, and each
        # node type is a different subclass of `Tree`. Thus two trees whose roots have
        # different types do not get the diff.
        if isinstance(first, Tree) and isinstance(second, Tree):
            if first != second:
                diff = ocdiff.console_diff(first.pretty, second.pretty)
                message = diff if msg is None else f"{msg}\n{diff}"
                raise self.failureException(message)
        else:
            super().assertEqual(first, second, msg)

    def assertIsDefined[U](self, value: U | None) -> U:
        __tracebackhide__ = True
        self.assertIsNotNone(value)
        return cast(U, value)


class FakeDocumentTestCase(TreeTestCase):
    fake_uri = "file:///tmp/test.jsonnet"

    def fake_document(self, source: str) -> FakeDocument:
        return FakeDocument(source, uri=self.fake_uri)


class FakeWorkspaceTestCase(TreeTestCase):
    root: Path
    source_config: SourcesConfig

    @override
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.source_config = SourcesConfig()
        self.addTypeEqualityFunc(ImportGraph, self.assertImportGraphEqual)

    def assertImportGraphEqual(
        self,
        first: ImportGraph,
        second: ImportGraph,
        msg: str | None = None,
    ):
        __tracebackhide__ = True

        if first != second:
            diff = ocdiff.console_diff(first.pretty, second.pretty)
            raise self.failureException(diff if msg is None else f"{msg}\n{diff}")

    def assertImportGraphInSync(self, graph: ImportGraph):
        __tracebackhide__ = True
        self.assertEqual(graph, self.build_import_graph())

    def build_import_graph(self) -> ImportGraph:
        return ImportGraph.build(self.root, self.source_config)

    def delete(self, *paths: str | Path):
        for path in paths:
            self.root.joinpath(path).unlink()

    def file(self, path: str | Path, text: str = "") -> FileEntry:
        return FileEntry(self.root.joinpath(path), text)

    def dir(self, path: str | Path) -> DirEntry:
        return DirEntry(self.root.joinpath(path))

    def symlink(self, link: str | Path, target: str | Path) -> SymLinkEntry:
        return SymLinkEntry(
            self.root.joinpath(link),
            self.root.joinpath(target),
        )

    def provision(self, *entries: FsEntry):
        for entry in entries:
            match entry:
                case DirEntry():
                    entry.path.mkdir(parents=True, exist_ok=True)

                case FileEntry(text=text):
                    entry.path.parent.mkdir(parents=True, exist_ok=True)
                    entry.path.write_text(text)

                case SymLinkEntry():
                    entry.path.parent.mkdir(parents=True, exist_ok=True)
                    entry.path.symlink_to(
                        entry.target,
                        target_is_directory=entry.target.is_dir(),
                    )

                case _:
                    raise TypeError(f"Unsupported layout entry: {entry!r}")

    @contextmanager
    def update_source_config(self, **kwargs):
        before = self.source_config
        self.source_config = self.source_config.model_copy(update=kwargs)

        try:
            yield
        finally:
            self.source_config = before

    @contextmanager
    def exclude(self, *patterns: str):
        with self.update_source_config(exclude=list(patterns)):
            yield

    @contextmanager
    def jpaths(self, *entries: str):
        with self.update_source_config(jpaths=list(entries)):
            yield

    def index_workspace(self, *entries: FsEntry) -> FolderIndex:
        self.provision(*entries)
        return FolderIndex(self.build_import_graph())
