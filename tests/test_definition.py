import unittest
from textwrap import dedent

from joule.ast import AST, Document, Id, enclosing_node
from joule.maybe import must
from joule.model.document_store import DocumentStore
from joule.providers.definition_provider import DefinitionProvider
from tests.dsl.fake_document import FakeDocument

from . import TempWorkspaceTestCase


class DefinitionTestCase(TempWorkspaceTestCase):
    def assertVarDefined(self, doc: FakeDocument, var_mark: int, ref_marks: list[int]):
        var_node = doc.node_at(doc.start_of(var_mark))
        self.assertIsInstance(var_node, Id.Var)

        store = self.workspace(doc)
        def_provider = DefinitionProvider(store)

        for ref_mark in ref_marks:
            self.assertSequenceEqual(
                def_provider.serve(doc.ast, doc.start_of(ref_mark)),
                [var_node.location],
            )

    def assertParamDefined(
        self,
        store: DocumentStore,
        params: list[AST],
        refs: list[AST],
    ):
        def_provider = DefinitionProvider(store)
        param_locations = [param.to(Id.Var).location for param in params]

        for ref in refs:
            ref_location = ref.to(Id.ParamRef).location
            tree = must(enclosing_node(ref, Document))
            self.assertSequenceEqual(
                def_provider.serve(tree, ref_location.range.start),
                param_locations,
            )

    def assertFieldDefined(
        self,
        store: DocumentStore,
        keys: list[AST],
        refs: list[AST],
    ):
        def_provider = DefinitionProvider(store)
        key_locations = [key.to(Id.Field).location for key in keys]

        for ref in refs:
            ref_location = ref.to(Id.FieldRef).location
            tree = must(enclosing_node(ref, Document))
            self.assertSequenceEqual(
                def_provider.serve(tree, ref_location.range.start),
                key_locations,
            )


class TestVarDefinition(DefinitionTestCase):
    def test_assert_expr(self):
        self.assertVarDefined(
            self.fake_document(
                dedent(
                    """\
                    local v = 1;
                          ^1
                    { f(): assert true; v }
                                        ^2
                    """
                )
            ),
            var_mark=1,
            ref_marks=[2],
        )

    def test_local(self):
        self.assertVarDefined(
            self.fake_document(
                dedent(
                    """\
                    local x = 1; x
                          ^1     ^2
                    """
                )
            ),
            var_mark=1,
            ref_marks=[2],
        )

    def test_local_shadowing(self):
        self.assertVarDefined(
            self.fake_document(
                dedent(
                    """\
                    local x = 1; local x = 2; x
                                       ^1     ^2
                    """
                )
            ),
            var_mark=1,
            ref_marks=[2],
        )

    def test_fn_params(self):
        t = self.fake_document(
            dedent(
                """
                function(p1=p2, p2, p3=p1) p1 + p2 + p3
                         ^1 ^2  ^3  ^4 ^5  ^6   ^7   ^8
                """
            )
        )

        self.assertVarDefined(t, var_mark=1, ref_marks=[5, 6])
        self.assertVarDefined(t, var_mark=3, ref_marks=[2, 7])
        self.assertVarDefined(t, var_mark=4, ref_marks=[8])

    def test_fn_params_field_fn(self):
        t = self.fake_document(
            dedent(
                """\
                { f(p1=p2, p2, p3=p1): p1 + p2 + p3 }
                    ^1 ^2  ^3  ^4 ^5   ^6   ^7   ^8
                """
            )
        )

        self.assertVarDefined(t, var_mark=1, ref_marks=[5, 6])
        self.assertVarDefined(t, var_mark=3, ref_marks=[2, 7])
        self.assertVarDefined(t, var_mark=4, ref_marks=[8])

    def test_list_comp(self):
        t = self.fake_document(
            dedent(
                """\
                [local v = 0; i + v for i in [2, 3]]
                       ^1     ^2  ^3    ^4
                """
            )
        )

        self.assertVarDefined(t, var_mark=1, ref_marks=[3])
        self.assertVarDefined(t, var_mark=4, ref_marks=[2])

    def test_obj_comp(self):
        t = self.fake_document(
            dedent(
                """\
                local v = 1;
                      ^1
                {
                    local v = 2,
                          ^2
                    ['f' + i + v]: v,
                           ^3  ^4  ^5
                    for i in [1, 2]
                        ^6
                }
                """
            )
        )

        self.assertVarDefined(t, var_mark=1, ref_marks=[4])
        self.assertVarDefined(t, var_mark=2, ref_marks=[5])
        self.assertVarDefined(t, var_mark=6, ref_marks=[3])

    def test_slice_var_index(self):
        t = self.fake_document(
            dedent(
                """\
                local f = 'f'; local v = { f: 0 }; v[f]
                      ^1             ^2            ^3^4
                """
            )
        )

        self.assertVarDefined(t, var_mark=1, ref_marks=[4])
        self.assertVarDefined(t, var_mark=2, ref_marks=[3])


class TestParamDefinition(DefinitionTestCase):
    def test_local_fn(self):
        t = self.fake_document(
            dedent(
                """\
                local f(p) = p + 1;
                        ^1
                f(p=1)
                  ^2
                """
            )
        )

        self.assertParamDefined(
            self.workspace(t),
            params=[t @ 1],
            refs=[t @ 2],
        )

    def test_field_fn(self):
        t = self.fake_document(
            dedent(
                """\
                local v = {
                    f(p): p + 1
                      ^1
                };
                v.f(p=1)
                    ^2
                """
            )
        )

        self.assertParamDefined(
            self.workspace(t),
            params=[t @ 1],
            refs=[t @ 2],
        )

    def test_local_fn_if(self):
        t = self.fake_document(
            dedent(
                """\
                local v =
                    if true
                    then { f(p): p + 1 }
                             ^1
                    else { f(p): p + 2 } ;
                             ^2
                v.f(p=1)
                    ^3
                """
            )
        )

        self.assertParamDefined(
            self.workspace(t),
            params=[t @ 1, t @ 2],
            refs=[t @ 3],
        )

    def test_imported_fn_call_arg(self):
        t1 = self.fake_document(
            dedent(
                """\
                function(p) = p + 1
                         ^1
                """
            ),
            "doc1.jsonnet",
        )

        t2 = self.fake_document(
            dedent(
                """\
                local f = import 'doc1.jsonnet';
                f(p=1)
                  ^1
                """
            ),
            "doc2.jsonnet",
        )

        self.assertParamDefined(
            self.workspace([t1, t2]),
            params=[t1 @ 1],
            refs=[t2 @ 1],
        )


class TestFieldDefinition(DefinitionTestCase):
    def test_local(self):
        t = self.fake_document(
            dedent(
                """\
                local v = { f: 0 }; v.f
                            ^1        ^2
                """
            )
        )

        self.assertFieldDefined(
            self.workspace(t),
            keys=[t @ 1],
            refs=[t @ 2],
        )

    def test_local_nested_field(self):
        t = self.fake_document(
            dedent(
                """\
                local v = { f: { g: 0 } }; v.f.g
                            ^1   ^2          ^3^4
                """
            )
        )

        self.assertFieldDefined(
            self.workspace(t),
            keys=[t @ 1],
            refs=[t @ 3],
        )

        self.assertFieldDefined(
            self.workspace(t),
            keys=[t @ 2],
            refs=[t @ 4],
        )

    def test_dollar(self):
        t = self.fake_document(
            dedent(
                """\
                { f: 1, g: { h: $.i, i: 2 }, i: 3 }
                                  ^1         ^2
                """
            )
        )

        self.assertFieldDefined(
            self.workspace(t),
            keys=[t @ 2],
            refs=[t @ 1],
        )

    def test_local_if(self):
        t = self.fake_document(
            dedent(
                """\
                local v = if true then { f: 1 } else { f: 2 }; v.f
                                         ^1            ^2        ^3
                """
            )
        )

        self.assertFieldDefined(
            self.workspace(t),
            keys=[t @ 1, t @ 2],
            refs=[t @ 3],
        )

    def test_local_if_no_else(self):
        t = self.fake_document(
            dedent(
                """\
                local v = if true then { f: 1 }; v.f
                                         ^1        ^2
                """
            )
        )

        self.assertFieldDefined(
            self.workspace(t),
            keys=[t @ 1],
            refs=[t @ 2],
        )

    def test_local_if_in_var(self):
        t = self.fake_document(
            dedent(
                """\
                local v1 = { f: 1 };
                             ^1
                local v2 = { f: 2 };
                             ^2
                local v3 = if true then v1 else v2;
                v3.f
                   ^3
                """
            )
        )

        self.assertFieldDefined(
            self.workspace(t),
            keys=[t @ 1, t @ 2],
            refs=[t @ 3],
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
                { f: 2 }
                  ^1
                """
            ),
            "doc2.jsonnet",
        )

        t3 = self.fake_document(
            dedent(
                """\
                if true
                then import "doc1.jsonnet"
                else import "doc2.jsonnet"
                """
            ),
            "doc3.jsonnet",
        )

        t4 = self.fake_document(
            dedent(
                """\
                (import "doc3.jsonnet").f
                                        ^1
                """
            ),
            "doc4.jsonnet",
        )

        self.assertFieldDefined(
            self.workspace(docs=[t1, t2, t3, t4]),
            keys=[t1 @ 1, t2 @ 1],
            refs=[t4 @ 1],
        )

    def test_self(self):
        t = self.fake_document(
            """\
            { local root = self, f(p): p, g: root.f(1) }
                                 ^1               ^2
            """
        )

        self.assertFieldDefined(
            self.workspace(t),
            keys=[t @ 1],
            refs=[t @ 2],
        )

    def test_obj_extend(self):
        t = self.fake_document(
            """\
            local v1 = { func(p): p + 1 };
            local v2 = { func(p): p + 2 };
                         ^1   ^2
            (v1 + v2).func(p=1)
                      ^3   ^4
            """
        )

        w = self.workspace(t)

        self.assertFieldDefined(
            w,
            keys=[t @ 1],
            refs=[t @ 3],
        )

        self.assertParamDefined(
            w,
            params=[t @ 2],
            refs=[t @ 4],
        )

    def test_for_spec(self):
        t = self.fake_document(
            """\
            [
                v.f for v in [{ f: 1 }, { f: 2 }]
                  ^1            ^2        ^3
            ]
            """
        )

        self.assertFieldDefined(
            self.workspace(t),
            keys=[t @ 2, t @ 3],
            refs=[t @ 1],
        )


class TestParamFieldDefinition(DefinitionTestCase):
    def test_literal_arg(self):
        t = self.fake_document(
            dedent(
                """\
                local f(p) = p.f;
                               ^1
                f({ f: 1 })
                    ^2
                """
            )
        )

        self.assertFieldDefined(
            self.workspace(t),
            keys=[t @ 2],
            refs=[t @ 1],
        )

    def test_local_var_arg(self):
        t = self.fake_document(
            dedent(
                """\
                local f(p) = p.f;
                               ^1
                local v = { f: 1 };
                            ^2
                f(v)
                """
            )
        )

        self.assertFieldDefined(
            self.workspace(t),
            keys=[t @ 2],
            refs=[t @ 1],
        )

    def test_imported_fn(self):
        t1 = self.fake_document(
            dedent(
                """\
                function(p) p.f
                              ^1
                """
            ),
            "doc1.jsonnet",
        )

        t2 = self.fake_document(
            dedent(
                """\
                local f = import 'doc1.jsonnet';
                f({ f: 2 })
                    ^1
                """
            ),
            "doc2.jsonnet",
        )

        self.assertFieldDefined(
            self.workspace(docs=[t1, t2]),
            keys=[t2 @ 1],
            refs=[t1 @ 1],
        )

    def test_imported_fn_param_default(self):
        t1 = self.fake_document(
            dedent(
                """\
                function(p={ f: 1 }) p.f
                             ^1        ^2
                """
            ),
            "doc1.jsonnet",
        )

        t2 = self.fake_document(
            dedent(
                """\
                local f = import 'doc1.jsonnet';
                f({ f: 2 })
                    ^1
                """
            ),
            "doc2.jsonnet",
        )

        self.assertFieldDefined(
            self.workspace([t1, t2]),
            keys=[t1 @ 1, t2 @ 1],
            refs=[t1 @ 2],
        )

    def test_param_default(self):
        t = self.fake_document(
            """\
            function(p={ f: 1 }) p.f
                         ^1        ^2
            """
        )

        self.assertFieldDefined(
            self.workspace(t),
            keys=[t @ 1],
            refs=[t @ 2],
        )

    def test_field_fn_param_default(self):
        t = self.fake_document(
            """\
            { f(p={ f: 1 }): p.f }
                    ^1         ^2
            """
        )

        self.assertFieldDefined(
            self.workspace(t),
            keys=[t @ 1],
            refs=[t @ 2],
        )

    def test_fn_returned_fn(self):
        t = self.fake_document(
            dedent(
                """\
                local f(p) = p.f;
                               ^1
                local g() = f;
                g()({ f: 1 })
                      ^2
                """
            )
        )

        self.assertFieldDefined(
            self.workspace(t),
            keys=[t @ 2],
            refs=[t @ 1],
        )

    @unittest.skip("FIXME")
    def test_field_fn_of_param(self):
        t = self.fake_document(
            dedent(
                """\
                function(p) p.f()
                              ^1
                """
            )
        )

        self.assertFieldDefined(
            self.workspace(t),
            keys=[],
            refs=[t @ 1],
        )
