import os
import tempfile
import unittest
from pathlib import Path

from joule.analysis.imports import (
    CachedImportResolver,
    ImportGraphBuilder,
    ImportResolver,
)


class Cases:
    # Nested so that test runners collect only the concrete subclasses below.
    class ResolveImportee(unittest.TestCase):
        resolver_class: type[ImportResolver]

        def setUp(self):
            tmp = tempfile.TemporaryDirectory()
            self.addCleanup(tmp.cleanup)
            self.root = Path(tmp.name).resolve()

        def touch(self, *paths: str):
            for path in paths:
                (self.root / path).parent.mkdir(parents=True, exist_ok=True)
                (self.root / path).touch()

        def resolve(self, importer: str, importee: str, jpaths: tuple[str, ...] = ()):
            resolver = self.resolver_class(self.root, [Path(p) for p in jpaths])
            return resolver.resolve(Path(importer), importee)

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
                self.resolve(
                    "ci/builds/main.jsonnet", "ci/utils.jsonnet.TEMPLATE", (".",)
                ),
                self.root / "ci/utils.jsonnet.TEMPLATE",
            )

        def test_absolute_importee(self):
            self.touch("a/main.jsonnet", "b/lib.libsonnet")
            self.assertEqual(
                self.resolve(
                    "a/main.jsonnet", str(self.root / "b/lib.libsonnet"), ("a",)
                ),
                self.root / "b/lib.libsonnet",
            )

        def test_unresolved(self):
            self.touch("a/main.jsonnet")
            self.assertIsNone(
                self.resolve("a/main.jsonnet", "missing.libsonnet", (".",))
            )

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


class TestImportResolver(Cases.ResolveImportee):
    resolver_class = ImportResolver


class TestCachedImportResolver(Cases.ResolveImportee):
    resolver_class = CachedImportResolver


# A workspace covering every case of `ImportGraphBuilder.build`. Building starts a process
# pool, so it is built once for all of `TestImportGraphBuilder`.
BUILD_FILES = {
    # Imports `lib.libsonnet` twice, which must yield a single edge.
    "app/main.jsonnet": """
        local lib = import "lib.libsonnet";
        local again = import "lib.libsonnet";
        local vendored = import "v.libsonnet";
        local data = import "data.json";
        local missing = import "missing.libsonnet";
        local text = importstr "notes.txt";
        local blob = importbin "blob.bin";
        [lib, again, vendored, data, missing, text, blob]
    """,
    "app/lib.libsonnet": "{}",
    "app/data.json": "{}",
    "app/notes.txt": "notes",
    "app/blob.bin": "blob",
    "vendor/v.libsonnet": "{}",
    # Fails to parse, but still contains a resolvable import.
    "app/broken.jsonnet": 'local x = import "lib.libsonnet"; {',
    "app/standalone.jsonnet": "{}",
}

BUILD_DOCS = [
    "app/main.jsonnet",
    "app/lib.libsonnet",
    "vendor/v.libsonnet",
    "app/broken.jsonnet",
    "app/standalone.jsonnet",
    # Listed by discovery but gone by the time the graph is built.
    "app/deleted.jsonnet",
]


class TestImportGraphBuilder(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        cls.root = Path(tmp.name).resolve()

        for path, text in BUILD_FILES.items():
            (cls.root / path).parent.mkdir(parents=True, exist_ok=True)
            (cls.root / path).write_text(text)

        docs = [cls.root / doc for doc in BUILD_DOCS]
        cls.graph = ImportGraphBuilder(cls.root, [Path("vendor")]).build(docs)

    def path(self, rel: str) -> Path:
        return self.root / rel

    def imports_of(self, rel: str) -> set[Path]:
        return self.graph.imports.get(self.path(rel), set())

    def test_imports(self):
        self.assertEqual(
            self.imports_of("app/main.jsonnet"),
            {
                self.path("app/lib.libsonnet"),
                self.path("vendor/v.libsonnet"),
                self.path("app/data.json"),
            },
        )

    def test_imported_by_mirrors_imports(self):
        inverted: dict[Path, set[Path]] = {}
        for importer, importees in self.graph.imports.items():
            for importee in importees:
                inverted.setdefault(importee, set()).add(importer)

        imported_by = {k: v for k, v in self.graph.imported_by.items() if v}
        self.assertEqual(imported_by, inverted)

    def test_duplicate_imports_yield_one_edge(self):
        self.assertEqual(
            self.graph.imported_by[self.path("app/lib.libsonnet")],
            {self.path("app/main.jsonnet")},
        )

    def test_resolves_through_importer_dir_and_jpaths(self):
        self.assertIn(
            self.path("app/lib.libsonnet"), self.imports_of("app/main.jsonnet")
        )
        self.assertIn(
            self.path("vendor/v.libsonnet"), self.imports_of("app/main.jsonnet")
        )

    def test_non_document_import_targets_are_nodes(self):
        # `data.json` is not a discovered document, but is still an import target.
        self.assertNotIn(
            self.path("app/data.json"), [self.root / d for d in BUILD_DOCS]
        )
        self.assertEqual(
            self.graph.imported_by[self.path("app/data.json")],
            {self.path("app/main.jsonnet")},
        )

    def test_unresolved_imports_yield_no_edge(self):
        self.assertNotIn(self.path("app/missing.libsonnet"), self.graph.imported_by)

    def test_importstr_and_importbin_are_ignored(self):
        self.assertNotIn(self.path("app/notes.txt"), self.graph.imported_by)
        self.assertNotIn(self.path("app/blob.bin"), self.graph.imported_by)

    def test_documents_without_imports_have_no_edges(self):
        self.assertEqual(self.imports_of("app/standalone.jsonnet"), set())
        self.assertEqual(self.imports_of("app/lib.libsonnet"), set())

    def test_malformed_documents(self):
        self.assertCountEqual(
            self.graph.malformed,
            [self.path("app/broken.jsonnet"), self.path("app/deleted.jsonnet")],
        )

    def test_malformed_documents_contribute_no_edges(self):
        self.assertEqual(self.imports_of("app/broken.jsonnet"), set())
        self.assertEqual(self.imports_of("app/deleted.jsonnet"), set())
