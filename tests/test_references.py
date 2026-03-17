from textwrap import dedent

from joule.ast import AST, Id
from joule.model.document_loader import DocumentLoader
from joule.providers import ReferencesProvider

from . import FakeWorkspaceTestCase
from .dsl import FakeDocument, fake_workspace


class TestReferences(FakeWorkspaceTestCase):
    def assertVarReferenced(
        self,
        doc: FakeDocument,
        var_mark: int,
        ref_marks: list[int],
    ):
        loader = self.workspace(doc)
        ref_provider = ReferencesProvider(loader)
        self.assertSequenceEqual(
            [doc.node_at(ref_mark) for ref_mark in ref_marks],
            list(ref_provider.find_references(doc.node_at(var_mark))),
        )

    def assertFieldReferenced(
        self,
        loader: DocumentLoader,
        field: AST,
        refs: list[AST],
    ):
        ref_provider = ReferencesProvider(loader)
        self.assertSequenceEqual(
            [ref.to(Id.FieldRef) for ref in refs],
            sorted(
                ref_provider.find_references(field.to(Id.Field)),
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

    def test_if(self):
        t = FakeDocument(
            dedent(
                """\
                function(p) if p > 0 then p else -p
                         ^1    ^2         ^3      ^4
                """
            )
        )

        self.assertVarReferenced(t, var_mark=1, ref_marks=[2, 3, 4])


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
            self.workspace(t),
            field=t @ 1,
            refs=[t @ 2],
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
            field=t1 @ 1,
            refs=[t2 @ 1, t3 @ 1],
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
            self.workspace(t),
            field=t @ 1,
            refs=[t @ 2],
        )
