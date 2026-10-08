import os
import tempfile
import unittest
from pathlib import Path

from joule.analysis.imports import ImportGraph


class TestResolveImportee(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()

    def touch(self, *paths: str):
        for path in paths:
            (self.root / path).parent.mkdir(parents=True, exist_ok=True)
            (self.root / path).touch()

    def resolve(self, importer: str, importee: str, jpaths: tuple[str, ...] = ()):
        graph = ImportGraph(self.root, [Path(p) for p in jpaths], [])
        return graph.resolve_importee(Path(importer), importee)

    def test_relative_to_importer(self):
        self.touch("a/main.jsonnet", "a/lib.libsonnet")
        self.assertEqual(
            self.resolve("a/main.jsonnet", "lib.libsonnet"),
            self.root / "a/lib.libsonnet",
        )

    def test_dots_are_collapsed(self):
        self.touch("a/main.jsonnet", "b/lib.libsonnet")
        self.assertEqual(
            self.resolve("a/main.jsonnet", "../b/./lib.libsonnet"),
            self.root / "b/lib.libsonnet",
        )

    def test_importer_dir_before_jpath(self):
        self.touch("a/main.jsonnet", "a/lib.libsonnet", "vendor/lib.libsonnet")
        self.assertEqual(
            self.resolve("a/main.jsonnet", "lib.libsonnet", ("vendor",)),
            self.root / "a/lib.libsonnet",
        )

    def test_falls_back_to_jpath(self):
        self.touch("a/main.jsonnet", "vendor/lib.libsonnet")
        self.assertEqual(
            self.resolve("a/main.jsonnet", "lib.libsonnet", ("vendor",)),
            self.root / "vendor/lib.libsonnet",
        )

    def test_later_jpath_wins(self):
        self.touch("a/main.jsonnet", "j1/lib.libsonnet", "j2/lib.libsonnet")
        self.assertEqual(
            self.resolve("a/main.jsonnet", "lib.libsonnet", ("j1", "j2")),
            self.root / "j2/lib.libsonnet",
        )

    def test_workspace_root_as_jpath(self):
        self.touch("ci/builds/main.jsonnet", "ci/utils.jsonnet.TEMPLATE")
        self.assertEqual(
            self.resolve("ci/builds/main.jsonnet", "ci/utils.jsonnet.TEMPLATE", (".",)),
            self.root / "ci/utils.jsonnet.TEMPLATE",
        )

    def test_absolute_importee(self):
        self.touch("a/main.jsonnet", "b/lib.libsonnet")
        self.assertEqual(
            self.resolve("a/main.jsonnet", str(self.root / "b/lib.libsonnet"), ("a",)),
            self.root / "b/lib.libsonnet",
        )

    def test_unresolved(self):
        self.touch("a/main.jsonnet")
        self.assertIsNone(self.resolve("a/main.jsonnet", "missing.libsonnet", (".",)))

    def test_symlinks_are_not_followed(self):
        # `link` points to `real/sub`. Lexically, `link/../lib.libsonnet` is
        # `lib.libsonnet` under the root, not `real/lib.libsonnet`.
        self.touch("real/sub/main.jsonnet", "real/lib.libsonnet", "lib.libsonnet")
        os.symlink(self.root / "real/sub", self.root / "link")
        self.assertEqual(
            self.resolve("link/main.jsonnet", "../lib.libsonnet"),
            self.root / "lib.libsonnet",
        )

    def test_jpath_candidates_are_normalized_before_existence_check(self):
        # Under `j2`, `link/../x.libsonnet` exists only physically, through the link to
        # `elsewhere/sub` (as `elsewhere/x.libsonnet`). Lexically it's `j2/x.libsonnet`,
        # which doesn't exist, so the lower-priority `j1` must win.
        self.touch("a/main.jsonnet", "j1/x.libsonnet", "elsewhere/x.libsonnet")
        (self.root / "elsewhere/sub").mkdir()
        (self.root / "j2").mkdir()
        os.symlink(self.root / "elsewhere/sub", self.root / "j2/link")
        self.assertEqual(
            self.resolve("a/main.jsonnet", "link/../x.libsonnet", ("j1", "j2")),
            self.root / "j1/x.libsonnet",
        )
