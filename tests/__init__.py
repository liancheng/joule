import dataclasses as D
import shutil
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import override

import ocdiff

from joule.analysis.imports import ImportGraphBuilder
from joule.config import Config
from joule.syntax.trees import Tree
from joule.workspace import FolderIndex, discover_docs
from tests.dsl import FakeDocument


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


class FakeDocumentTestCase(TreeTestCase):
    fake_uri = "file:///tmp/test.jsonnet"

    def fake_document(self, source: str) -> FakeDocument:
        return FakeDocument(source, uri=self.fake_uri)


class FakeWorkspaceTestCase(TreeTestCase):
    root: Path
    current_config: Config

    @D.dataclass(frozen=True)
    class FsEntry:
        path: str | Path

    @D.dataclass(frozen=True)
    class File(FsEntry):
        content: str = ""

    @D.dataclass(frozen=True)
    class Dir(FsEntry):
        pass

    @D.dataclass(frozen=True)
    class SymLink(FsEntry):
        target: str | Path

    @override
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.current_config = Config()

    def rel_path(self, path_like: str | Path | FakeDocument) -> Path:
        path_like = path_like.path if isinstance(path_like, FakeDocument) else path_like
        return self.root.joinpath(path_like).relative_to(self.root)

    def purge(self):
        for child in self.root.iterdir():
            if child.is_dir(follow_symlinks=False):
                shutil.rmtree(child)
            else:
                child.unlink()

    def file(self, path: str | Path, content: str = "") -> File:
        return self.File(path, content)

    def dir(self, path: str | Path) -> Dir:
        return self.Dir(path)

    def symlink(self, link: str | Path, target: str | Path) -> SymLink:
        return self.SymLink(link, target)

    def provision(self, *entries: FsEntry):
        for entry in entries:
            path = self.root.joinpath(entry.path)

            match entry:
                case self.Dir():
                    path.mkdir(parents=True, exist_ok=True)

                case self.File(content=content):
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(content)

                case self.SymLink(target=target):
                    path.parent.mkdir(parents=True, exist_ok=True)
                    target = self.root.joinpath(target)
                    path.symlink_to(target, target_is_directory=target.is_dir())

                case _:
                    raise TypeError(f"Unsupported layout entry: {entry!r}")

    @contextmanager
    def jpaths(self, *entries: str):
        before = self.current_config
        update = {"jpaths": list(entries)}
        self.current_config = self.current_config.model_copy(update=update)

        try:
            yield
        finally:
            self.current_config = before

    @contextmanager
    def layout(self, *entries: FsEntry):
        self.provision(*entries)

        try:
            yield
        finally:
            self.purge()

    def fake_document(self, source: str, path: str) -> FakeDocument:
        uri = self.root.joinpath(path).as_uri()
        return FakeDocument(source, uri=uri)

    @contextmanager
    def workspace(self, *docs: FakeDocument):
        self.provision(*(self.file(Path.from_uri(doc.uri), doc.text) for doc in docs))

        paths = discover_docs(
            self.root,
            self.current_config.extensions,
            self.current_config.exclude,
        )

        builder = ImportGraphBuilder(self.root, self.current_config.jpaths)
        graph = builder.build(paths)

        try:
            yield FolderIndex(graph)
        finally:
            self.purge()
