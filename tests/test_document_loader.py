from pathlib import Path

from pyfakefs.fake_filesystem_unittest import TestCase

from joule.model.document_loader import DocumentLoader


class TestDocumentLoader(TestCase):
    def setUp(self) -> None:
        self.setUpPyfakefs()

    def test_list_sources(self):
        root = Path("/tmp/project")

        self.fs.create_dir(root / ".git" / "baz.jsonnet")
        self.fs.create_file(root / "vendor" / "foo" / "bar" / "baz.jsonnet")
        self.fs.create_file(root / "vendor" / "foo" / "bar" / "baz.py")
        self.fs.create_file(root / "nested" / "vendor" / "foo" / "baz.jsonnet")

        loader = DocumentLoader(root.as_uri())
        self.assertSetEqual(
            set(
                loader.list_paths(
                    root,
                    include_globs=["**/vendor"],
                    exclude_globs=["**/.*"],
                    source_globs=["*.jsonnet"],
                )
            ),
            {
                root.joinpath("vendor", "foo", "bar", "baz.jsonnet"),
                root.joinpath("nested", "vendor", "foo", "baz.jsonnet"),
            },
        )
