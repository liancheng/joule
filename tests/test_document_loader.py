from pathlib import Path
from typing import Iterable

from pyfakefs.fake_filesystem_unittest import TestCase

from joule.config import JouleConfig
from joule.model.document_loader import DocumentLoader


class TestDocumentLoader(TestCase):
    def setUp(self) -> None:
        self.setUpPyfakefs()

        self.project_root = Path("/tmp/project")
        self.fs.create_dir(self.project_root)
        self.fs.create_file(self.project_root.joinpath(".git", "config"))
        self.fs.create_file(self.project_root.joinpath("src", "d", "__init__.py"))
        self.fs.create_file(self.project_root.joinpath("vendor", "d1", "f1.jsonnet"))
        self.fs.create_file(self.project_root.joinpath("vendor", "d2", "f2.libsonnet"))
        self.fs.create_file(self.project_root.joinpath("test", "test_f1.jsonnet"))

    def tearDown(self) -> None:
        self.tearDownPyfakefs()
        return super().tearDown()

    def assertPathsEqual(self, obtained: Iterable[Path], expected: Iterable[Path]):
        self.assertSequenceEqual(sorted(obtained), sorted(expected))

    def test_list_files(self):
        loader = DocumentLoader(
            self.project_root.as_uri(),
            JouleConfig(
                exclude=["**/.*"],
                include=["**/vendor/**"],
                suffixes=["jsonnet"],
            ),
        )

        self.assertPathsEqual(
            loader.list_source_files(self.project_root),
            [self.project_root.joinpath("vendor", "d1", "f1.jsonnet")],
        )

    def test_list_files_multi_source_globs(self):
        loader = DocumentLoader(
            self.project_root.as_uri(),
            JouleConfig(
                exclude=["**/.*"],
                include=["**/vendor/**"],
                suffixes=["jsonnet", "libsonnet"],
            ),
        )

        self.assertPathsEqual(
            loader.list_source_files(self.project_root),
            [
                self.project_root.joinpath("vendor", "d1", "f1.jsonnet"),
                self.project_root.joinpath("vendor", "d2", "f2.libsonnet"),
            ],
        )

    def test_list_library_search_paths(self):
        loader = DocumentLoader(
            self.project_root.as_uri(),
            JouleConfig(library_paths=["**/vendor"]),
        )

        self.assertPathsEqual(
            loader.list_library_search_paths(self.project_root),
            [
                self.project_root.joinpath("vendor"),
            ],
        )
