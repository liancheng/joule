from pathlib import Path

from joule.analysis.imports import ImportResolver
from joule.maybe import head_or_none, maybe
from tests import Dir, FakeWorkspaceTestCase, File, SymLink


class TestImportResolver(FakeWorkspaceTestCase):
    def assertResolved(
        self,
        *,
        importer: str | Path,
        importee: str | Path,
        resolved: str | Path | None,
    ):
        __tracebackhide__ = True
        resolver = ImportResolver(self.root, self.current_config.jpaths)
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
        with self.layout(
            File("a/main.jsonnet"),
            File("a/lib.libsonnet"),
        ):
            self.assertResolved(
                importer="a/main.jsonnet",
                importee="lib.libsonnet",
                resolved="a/lib.libsonnet",
            )

    def test_dots_collapsed(self):
        with self.layout(
            File("a/main.jsonnet"),
            File("b/lib.libsonnet"),
        ):
            self.assertResolved(
                importer="a/main.jsonnet",
                importee="../b/./lib.libsonnet",
                resolved="b/lib.libsonnet",
            )

    def test_same_dir_over_jpaths(self):
        with (
            self.jpaths("vendor"),
            self.layout(
                File("a/main.jsonnet"),
                File("a/lib.libsonnet"),
                File("vendor/lib.libsonnet"),
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
            self.layout(
                File("a/main.jsonnet"),
                File("vendor/lib.libsonnet"),
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
            self.layout(
                File("a/main.jsonnet"),
                File("j1/lib.libsonnet"),
                File("j2/lib.libsonnet"),
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
            self.layout(
                File("ci/builds/main.jsonnet"),
                File("ci/utils.libsonnet"),
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
            self.layout(
                File("b/lib.libsonnet"),
                File("a/main.jsonnet"),
            ),
        ):
            self.assertResolved(
                importer="a/main.jsonnet",
                importee=self.root.joinpath("b/lib.libsonnet"),
                resolved="b/lib.libsonnet",
            )

        with (
            self.jpaths("a"),
            self.layout(
                File("a/main.jsonnet"),
                File("a/lib.libsonnet"),
                Dir("a/sub"),
                File("lib.libsonnet"),
                SymLink("link", target="a/sub"),
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
            self.layout(
                File("a/main.jsonnet"),
            ),
        ):
            self.assertUnresolved(
                importer="a/main.jsonnet",
                importee="missing.libsonnet",
            )

    def test_symlinks(self):
        with self.layout(
            File("real/lib.libsonnet"),
            File("real/sub/main.jsonnet"),
            File("lib.libsonnet"),
            SymLink("link", target="real/sub"),
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
            self.layout(
                File("a/main.jsonnet"),
                Dir("elsewhere/sub"),
                File("elsewhere/x.libsonnet"),
                File("j1/x.libsonnet"),
                Dir("j2"),
                SymLink("j2/link", target="elsewhere/sub"),
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
