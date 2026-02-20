from textwrap import dedent

from pyfakefs.fake_filesystem_unittest import TestCase

from joule.ast import Id
from joule.model.document_loader import DocumentLoader
from joule.providers import ReferencesProvider
from tests.dsl.fake_document import FakeDocument, fake_workspace


class TestReferences(TestCase):
    def setUp(self) -> None:
        self.setUpPyfakefs()

    def assertVarReferenced(
        self,
        doc: FakeDocument,
        var_mark: int,
        ref_marks: list[int],
    ):
        loader = fake_workspace(self.fs, doc)
        ref_provider = ReferencesProvider(loader)
        self.assertSequenceEqual(
            [doc.node_at(ref_mark) for ref_mark in ref_marks],
            list(ref_provider.find_references(doc.node_at(var_mark))),
        )

    def assertFieldReferenced(
        self,
        loader: DocumentLoader,
        field: Id.Field,
        refs: list[Id.FieldRef],
    ):
        ref_provider = ReferencesProvider(loader)
        self.assertSequenceEqual(
            refs,
            sorted(
                ref_provider.find_references(field),
                key=lambda ref: ref.location.uri,
            ),
        )


class TestVarReferences(TestReferences):
    def test_local(self):
        self.assertVarReferenced(
            FakeDocument(
                dedent(
                    """\
                    local v = 1; v
                          ^1     ^2
                    """
                )
            ),
            var_mark=1,
            ref_marks=[2],
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

        self.assertFieldReferenced(
            fake_workspace(self.fs, t),
            field=t.node_at(1).to(Id.Field),
            refs=[t.node_at(2).to(Id.FieldRef)],
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

        self.assertFieldReferenced(
            fake_workspace(
                self.fs,
                docs=[t1, t2, t3],
                root_uri="file:///tmp",
            ),
            field=t1.node_at(1).to(Id.Field),
            refs=[
                t2.node_at(1).to(Id.FieldRef),
                t3.node_at(1).to(Id.FieldRef),
            ],
        )

    def test_call(self):
        t = FakeDocument(
            dedent(
                """\
                local fn() = { f: 1 }; fn().f
                               ^1           ^2
                """
            )
        )

        self.assertFieldReferenced(
            fake_workspace(self.fs, t),
            field=t.node_at(1).to(Id.Field),
            refs=[t.node_at(2).to(Id.FieldRef)],
        )
