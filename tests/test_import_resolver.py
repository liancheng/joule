from pathlib import Path

from joule.analysis.imports import ImportResolver
from joule.maybe import maybe, optional
from tests import FakeWorkspaceTestCase


class TestImportResolver(FakeWorkspaceTestCase):
    def assertResolved(
        self,
        *,
        importer: str | Path,
        importee: str,
        resolved: str | Path | None,
    ):
        __tracebackhide__ = True
        resolver = ImportResolver(self.root, self.source_config.jpaths)
        self.assertEqual(
            resolver.resolve(Path(importer), importee),
            optional(self.root.joinpath(path) for path in maybe(resolved)),
        )

    def assertNotResolved(
        self,
        *,
        importer: str | Path,
        importee: str | Path,
    ):
        __tracebackhide__ = True
        self.assertResolved(importer=importer, importee=importee, resolved=None)

    def test_relative_to_importer(self):
        self.provision(
            self.file("a/main.jsonnet"),
            self.file("a/lib.libsonnet"),
        )

        self.assertResolved(
            importer="a/main.jsonnet",
            importee="lib.libsonnet",
            resolved="a/lib.libsonnet",
        )

    def test_dots_collapsed(self):
        self.provision(
            self.file("a/main.jsonnet"),
            self.file("b/lib.libsonnet"),
        )

        self.assertResolved(
            importer="a/main.jsonnet",
            importee="../b/./lib.libsonnet",
            resolved="b/lib.libsonnet",
        )

    def test_dots_escape_subdir(self):
        self.provision(
            self.file("a/b/main.jsonnet"),
            self.file("x.libsonnet"),
        )

        self.assertResolved(
            importer="a/b/main.jsonnet",
            importee="../../x.libsonnet",
            resolved="x.libsonnet",
        )

    def test_dots_above_workspace_root(self):
        self.provision(f1 := self.file("f1.libsonnet"))

        with self.workspace_root("d1"):
            self.provision(self.file("d2/f2.jsonnet"))

            self.assertResolved(
                importer="d2/f2.jsonnet",
                importee="../../f1.libsonnet",
                resolved=f1.path.resolve(),
            )

    def test_dots_above_workspace_root_unresolved(self):
        self.provision(self.file("a/main.jsonnet"))

        self.assertNotResolved(
            importer="a/main.jsonnet",
            importee="../../x.libsonnet",
        )

    def test_trailing_slash_in_importee(self):
        # go-jsonnet removes the trailing `/` when it joins the paths. The C++
        # jsonnet rejects the import as a directory.
        self.provision(
            self.file("main.jsonnet"),
            self.file("lib.libsonnet"),
        )

        self.assertResolved(
            importer="main.jsonnet",
            importee="lib.libsonnet/",
            resolved="lib.libsonnet",
        )

    def test_same_dir_over_jpaths(self):
        self.provision(
            self.file("a/main.jsonnet"),
            self.file("a/lib.libsonnet"),
            self.file("vendor/lib.libsonnet"),
        )

        with self.jpaths("vendor"):
            self.assertResolved(
                importer="a/main.jsonnet",
                importee="lib.libsonnet",
                resolved="a/lib.libsonnet",
            )

    def test_jpath_fallback(self):
        self.provision(
            self.file("a/main.jsonnet"),
            self.file("vendor/lib.libsonnet"),
        )

        with self.jpaths("vendor"):
            self.assertResolved(
                importer="a/main.jsonnet",
                importee="lib.libsonnet",
                resolved="vendor/lib.libsonnet",
            )

    def test_later_jpath_wins(self):
        self.provision(
            self.file("a/main.jsonnet"),
            self.file("j1/lib.libsonnet"),
            self.file("j2/lib.libsonnet"),
        )

        with self.jpaths("j1", "j2"):
            self.assertResolved(
                importer="a/main.jsonnet",
                importee="lib.libsonnet",
                resolved="j2/lib.libsonnet",
            )

    def test_workspace_root_as_jpath(self):
        self.provision(
            self.file("ci/builds/main.jsonnet"),
            self.file("ci/utils.libsonnet"),
        )

        with self.jpaths("."):
            self.assertResolved(
                importer="ci/builds/main.jsonnet",
                importee="ci/utils.libsonnet",
                resolved="ci/utils.libsonnet",
            )

    def test_absolute_importee(self):
        self.provision(
            self.file("b/lib.libsonnet"),
            self.file("a/main.jsonnet"),
        )

        with self.jpaths("a"):
            self.assertResolved(
                importer="a/main.jsonnet",
                importee=self.root.joinpath("b/lib.libsonnet"),
                resolved="b/lib.libsonnet",
            )

        self.provision(
            self.file("a/main.jsonnet"),
            self.file("a/lib.libsonnet"),
            self.dir("a/sub"),
            self.file("lib.libsonnet"),
            self.symlink("link", target="a/sub"),
        )

        with self.jpaths("a"):
            self.assertResolved(
                importer="a/main.jsonnet",
                importee=self.root.joinpath("link/../lib.libsonnet"),
                # Absolute importee paths are returned as is without normalization.
                resolved="link/../lib.libsonnet",
            )

    def test_unresolved(self):
        self.provision(
            self.file("d/f.jsonnet"),
        )

        with self.jpaths("."):
            self.assertNotResolved(
                importer="d/f.jsonnet",
                importee="missing.libsonnet",
            )

    # Joule removes `..` as text, like go-jsonnet. The C++ jsonnet and jrsonnet
    # resolve `..` through the OS, and follow symlinks. Thus these tests expect the
    # results of go-jsonnet, not the results of the other two.

    def test_symlinked_file(self):
        self.provision(
            self.file("d1/d2/f1.jsonnet"),
            self.file("d1/f2.libsonnet"),
            self.file("f2.libsonnet"),
            self.symlink("d3", "d1/d2"),
        )

        self.assertResolved(
            importer="d3/f1.jsonnet",
            importee="../f2.libsonnet",
            # Check importer directory:
            #   => {root}/d3/../f2.libsonnet
            #   => {root}/f2.libsonnet
            resolved="f2.libsonnet",
        )

    def test_symlinked_dir_in_jpath(self):
        self.provision(
            self.file("d1/f1.jsonnet"),
            self.dir("d2/d3"),
            self.file("d2/f2.libsonnet"),
            self.file("j1/f2.libsonnet"),
            self.dir("j2"),
            self.symlink("j2/link", "d2/d3"),
        )

        with self.jpaths("j1", "j2"):
            self.assertResolved(
                importer="d1/f1.jsonnet",
                importee="link/../f2.libsonnet",
                # Check importer directory:
                #   => {root}/d1/link/../f2.libsonnet
                #   => {root}/d1/f2.libsonnet
                #   => Not found
                #
                # Check jpath "j2":
                #   => {root}/j2/link/../f2.libsonnet
                #   => {root}/j2/f2.libsonnet
                #   => Not found
                #
                # Check jpath "j1":
                #   => {root}/j1/link/../f2.libsonnet
                #   => {root}/j1/f2.libsonnet
                #   => Found
                resolved="j1/f2.libsonnet",
            )
