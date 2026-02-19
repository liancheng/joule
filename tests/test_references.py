from textwrap import dedent

from pyfakefs.fake_filesystem_unittest import TestCase

from joule.providers import ReferencesProvider
from tests.dsl.fake_document import FakeDocument, fake_workspace


class TestReferences(TestCase):
    def setUp(self) -> None:
        self.setUpPyfakefs()


class TestVarReferences(TestReferences):
    def test_local(self):
        t = FakeDocument(
            dedent(
                """\
                local v = 1; v
                      ^1     ^2
                """
            )
        )

        loader = fake_workspace(self.fs, t)
        provider = ReferencesProvider(loader)

        self.assertSequenceEqual(
            list(provider.find_references(t.node_at(1))),
            [t.node_at(2)],
        )


class TestFieldReferences(TestReferences):
    def test_local(self):
        t = FakeDocument(
            dedent(
                """\
                local v = { f: 1 }; v.f
                            ^1        ^2
                """
            )
        )

        loader = fake_workspace(self.fs, t)
        provider = ReferencesProvider(loader)

        self.assertSequenceEqual(
            list(provider.find_references(t.node_at(1))),
            [t.node_at(2)],
        )

    def test_import(self):
        t1 = FakeDocument(
            dedent(
                """\
                { f: 1 }
                  ^1
                """
            ),
            uri="file:///tmp/doc1.jsonnet",
        )

        t2 = FakeDocument(
            dedent(
                """\
                (import "doc1.jsonnet").f
                                        ^1
                """
            ),
            uri="file:///tmp/doc2.jsonnet",
        )

        t3 = FakeDocument(
            dedent(
                """\
                (import "doc1.jsonnet").f
                                        ^1
                """
            ),
            uri="file:///tmp/doc3.jsonnet",
        )

        loader = fake_workspace(
            self.fs,
            docs=[t1, t2, t3],
            root_uri="file:///tmp",
        )

        self.assertSequenceEqual(
            list(ReferencesProvider(loader).find_references(t1.node_at(1))),
            [t2.node_at(1), t3.node_at(1)],
        )
