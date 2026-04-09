from textwrap import dedent

from joule.ast import AST, Id
from joule.model import DocumentStore
from joule.providers import ReferencesProvider

from . import TempWorkspaceTestCase
from .dsl import FakeDocument


class ReferencesTestCase(TempWorkspaceTestCase):
    def assertVarReferenced(
        self,
        doc: FakeDocument,
        var_mark: int,
        ref_marks: list[int],
    ):
        store = self.fake_workspace(doc)
        ref_provider = ReferencesProvider(store)
        self.assertSequenceEqual(
            [doc.node_at(ref_mark) for ref_mark in ref_marks],
            list(ref_provider.find_references(doc.node_at(var_mark))),
        )

    def assertFieldReferenced(
        self,
        store: DocumentStore,
        field: AST,
        refs: list[AST],
    ):
        ref_provider = ReferencesProvider(store)
        self.assertSequenceEqual(
            [ref.to(Id.FieldRef) for ref in refs],
            sorted(
                ref_provider.find_references(field.to(Id.Field)),
                key=lambda ref: ref.location.uri,
            ),
        )


class TestVarReferences(ReferencesTestCase):
    def test_local(self):
        self.assertVarReferenced(
            self.fake_document(
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
        t = self.fake_document(
            dedent(
                """\
                function(p) if p > 0 then p else -p
                         ^1    ^2         ^3      ^4
                """
            )
        )

        self.assertVarReferenced(t, var_mark=1, ref_marks=[2, 3, 4])


class TestFieldReferences(ReferencesTestCase):
    def test_local(self):
        t = self.fake_document(
            dedent(
                """\
                local v = { f: 1 }; v.f
                            ^1        ^2
                """
            )
        )

        self.assertFieldReferenced(
            self.fake_workspace(t),
            field=t.node_at(1),
            refs=[t.node_at(2)],
        )

    def test_import(self):
        t1 = self.fake_document(
            dedent(
                """\
                { f: 1 }
                  ^1
                """
            ),
            "doc1.jsonnet",
        )

        t2 = self.fake_document(
            dedent(
                """\
                (import "doc1.jsonnet").f
                                        ^1
                """
            ),
            "doc2.jsonnet",
        )

        t3 = self.fake_document(
            dedent(
                """\
                (import "doc1.jsonnet").f
                                        ^1
                """
            ),
            "doc3.jsonnet",
        )

        self.assertFieldReferenced(
            self.fake_workspace([t1, t2, t3]),
            field=t1.node_at(1),
            refs=[t2.node_at(1), t3.node_at(1)],
        )

    def test_call(self):
        t = self.fake_document(
            dedent(
                """\
                local fn() = { f: 1 }; fn().f
                               ^1           ^2
                """
            )
        )

        self.assertFieldReferenced(
            self.fake_workspace(t),
            field=t.node_at(1),
            refs=[t.node_at(2)],
        )
