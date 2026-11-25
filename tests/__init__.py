import errno
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
from tests.dsl import (
    Dir,
    FakeDocument,
    File,
    Provisionable,
    Symlink,
)


class TreeTestCase(unittest.TestCase):
    @override
    def assertEqual(self, first, second, msg=None):
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
    # The URI Neovim picks for documents in unsaved buffer.
    fake_uri = "file://"

    def fake_document(self, source: str) -> FakeDocument:
        return FakeDocument(source, uri=self.fake_uri)


class FakeWorkspaceTestCase(TreeTestCase):
    sandbox_root: Path
    root: Path
    source_config: SourcesConfig

    @override
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.sandbox_root = Path(tmp.name).resolve()
        self.root = self.sandbox_root
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
        self.assertEqual(graph, self._build_import_graph())

    def assertImports(
        self,
        index: FolderIndex,
        *,
        importer: File,
        importees: list[File],
    ):
        __tracebackhide__ = True

        g = index.import_graph

        self.assertSetEqual(
            g.imports_of(importer.path),
            {importee.path for importee in importees},
        )

        for importee in importees:
            self.assertIn(importer.path, g.importers_of(importee.path))
            self.assertIn(importee.path, g.imports_of(importer.path))

    def _build_import_graph(self) -> ImportGraph:
        return ImportGraph.build(self.root, self.source_config)

    def delete(self, *paths: str | Path):
        for path in paths:
            self.root.joinpath(path).unlink()

    def file(self, path: str | Path, text: str = "") -> File:
        return File(self.root.joinpath(path), text)

    def dir(self, path: str | Path) -> Dir:
        return Dir(self.root.joinpath(path))

    def symlink(self, link: str | Path, target: str | Path) -> Symlink:
        return Symlink(
            self.root.joinpath(link),
            self.root.joinpath(target),
        )

    def provision(self, *entries: Provisionable):
        for entry in entries:
            if not entry.path.is_relative_to(self.sandbox_root):
                raise ValueError(
                    f"{entry.path} is outside the test sandbox {self.sandbox_root}"
                )

            match entry:
                case Symlink() if not entry.target.exists():
                    raise FileNotFoundError(
                        errno.ENOENT,
                        "Symlink target not found",
                        entry.target.as_posix(),
                    )

                case _:
                    entry.provision()

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

    @contextmanager
    def workspace_root(self, root: Path | str):
        before = self.root
        self.root = self.root.joinpath(root)

        try:
            yield
        finally:
            self.root = before

    def fake_document(self, path: str, source: str) -> FakeDocument:
        return FakeDocument(source, self.root.joinpath(path).as_uri())

    def workspace(self, *entries: Provisionable) -> FolderIndex:
        self.provision(*entries)
        return FolderIndex(self._build_import_graph())
