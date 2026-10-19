import shutil
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from joule.analysis.imports import ImportGraphBuilder, ImportResolver
from joule.maybe import head_or_none, maybe


class TestImportResolver(unittest.TestCase):
    root: Path
    current_jpaths: list[Path]

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.current_jpaths = []

    def touch(self, *paths: str):
        for path in paths:
            self.root.joinpath(path).parent.mkdir(parents=True, exist_ok=True)
            self.root.joinpath(path).touch()

    @contextmanager
    def provision(self, *entries: str):
        for entry in entries:
            match entry.split(" -> "):
                case [str(dir)] if dir.endswith("/"):
                    self.root.joinpath(dir).mkdir(parents=True, exist_ok=True)

                case [str(file)]:
                    path = self.root.joinpath(file)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.touch(exist_ok=True)

                case [str(link), str(target)]:
                    self.root.joinpath(link).symlink_to(
                        target,
                        target_is_directory=self.root.joinpath(target).is_dir(),
                    )

                case _:
                    raise ValueError(
                        'A provisioned entry must be a file ("file_name") a directory'
                        ' ("dir_name/"), or a symlink ("link -> target").'
                    )

        try:
            yield
        finally:
            for child in self.root.iterdir():
                if child.is_dir(follow_symlinks=False):
                    shutil.rmtree(child)
                else:
                    child.unlink()

    @contextmanager
    def jpaths(self, *entries: str):
        before = self.current_jpaths
        self.current_jpaths = list(map(Path, entries))
        try:
            yield
        finally:
            self.current_jpaths = before

    def assertResolved(
        self,
        *,
        importer: str | Path,
        importee: str | Path,
        resolved: str | Path | None,
    ):
        __tracebackhide__ = True
        resolver = ImportResolver(self.root, self.current_jpaths)
        self.assertEqual(
            head_or_none(
                path.absolute().relative_to(self.root)
                for path in maybe(resolver.resolve(Path(importer), str(importee)))
            ),
            head_or_none(
                self.root.joinpath(path).absolute().relative_to(self.root)
                for path in maybe(resolved)
            ),
        )

    def assertUnresolved(
        self,
        *,
        importer: str | Path,
        importee: str | Path,
    ):
        __tracebackhide__ = True
        self.assertResolved(importer=importer, importee=importee, resolved=None)

    def test_relative_to_importer(self):
        with self.provision(
            "a/main.jsonnet",
            "a/lib.libsonnet",
        ):
            self.assertResolved(
                importer="a/main.jsonnet",
                importee="lib.libsonnet",
                resolved="a/lib.libsonnet",
            )

    def test_dots_collapsed(self):
        with self.provision(
            "a/main.jsonnet",
            "b/lib.libsonnet",
        ):
            self.assertResolved(
                importer="a/main.jsonnet",
                importee="../b/./lib.libsonnet",
                resolved="b/lib.libsonnet",
            )

    def test_same_dir_over_jpaths(self):
        with (
            self.jpaths("vendor"),
            self.provision(
                "a/main.jsonnet",
                "a/lib.libsonnet",
                "vendor/lib.libsonnet",
            ),
        ):
            self.assertResolved(
                importer="a/main.jsonnet",
                importee="lib.libsonnet",
                resolved="a/lib.libsonnet",
            )

    def test_jpath_fallback(self):
        with (
            self.jpaths("vendor"),
            self.provision(
                "a/main.jsonnet",
                "vendor/lib.libsonnet",
            ),
        ):
            self.assertResolved(
                importer="a/main.jsonnet",
                importee="lib.libsonnet",
                resolved="vendor/lib.libsonnet",
            )

    def test_later_jpath_wins(self):
        with (
            self.jpaths("j1", "j2"),
            self.provision(
                "a/main.jsonnet",
                "j1/lib.libsonnet",
                "j2/lib.libsonnet",
            ),
        ):
            self.assertResolved(
                importer="a/main.jsonnet",
                importee="lib.libsonnet",
                resolved="j2/lib.libsonnet",
            )

    def test_workspace_root_as_jpath(self):
        with (
            self.jpaths("."),
            self.provision(
                "ci/builds/main.jsonnet",
                "ci/utils.libsonnet",
            ),
        ):
            self.assertResolved(
                importer="ci/builds/main.jsonnet",
                importee="ci/utils.libsonnet",
                resolved="ci/utils.libsonnet",
            )

    def test_absolute_importee(self):
        with (
            self.jpaths("a"),
            self.provision(
                "b/lib.libsonnet",
                "a/main.jsonnet",
            ),
        ):
            self.assertResolved(
                importer="a/main.jsonnet",
                importee=self.root.joinpath("b/lib.libsonnet"),
                resolved="b/lib.libsonnet",
            )

        with (
            self.jpaths("a"),
            self.provision(
                "a/main.jsonnet",
                "a/lib.libsonnet",
                "a/sub/",
                "lib.libsonnet",
                "link -> a/sub",
            ),
        ):
            self.assertResolved(
                importer="a/main.jsonnet",
                importee=self.root.joinpath("link/../lib.libsonnet"),
                # Absolute importee paths are returned as is without normalization.
                resolved="link/../lib.libsonnet",
            )

    def test_unresolved(self):
        with (
            self.jpaths("."),
            self.provision("a/main.jsonnet"),
        ):
            self.assertUnresolved(
                importer="a/main.jsonnet",
                importee="missing.libsonnet",
            )

    def test_symlinks(self):
        with self.provision(
            "real/lib.libsonnet",
            "real/sub/main.jsonnet",
            "lib.libsonnet",
            "link -> real/sub",
        ):
            self.assertResolved(
                importer="link/main.jsonnet",
                importee="../lib.libsonnet",
                # Check importer parent directory:
                #   => {root}/link/../lib.libsonnet
                #   => {root}/lib.libsonnet
                resolved="lib.libsonnet",
            )

        with (
            self.jpaths("j1", "j2"),
            self.provision(
                "a/main.jsonnet",
                "elsewhere/sub/",
                "elsewhere/x.libsonnet",
                "j1/x.libsonnet",
                "j2/",
                "j2/link -> elsewhere/sub",
            ),
        ):
            self.assertResolved(
                importer="a/main.jsonnet",
                importee="link/../x.libsonnet",
                # Check importer parent directory:
                #   => {root}/a/link/../x.libsonnet
                #   => {root}/a/x.libsonnet (Normalize)
                #   => Not found
                #
                # Check jpath "j2":
                #   => {root}/j2/x.libsonnet
                #   => Not found
                #
                # Check jpath "j1":
                #   => {root}/j1/x.libsonnet
                resolved="j1/x.libsonnet",
            )


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
