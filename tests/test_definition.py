import unittest
from textwrap import dedent

from joule.ast import AST, Id
from joule.maybe import must
from joule.model import DocumentLoader
from joule.providers import DefinitionProvider

from . import FakeWorkspaceTestCase
from .dsl import FakeDocument


class TestDefinition(FakeWorkspaceTestCase):
    def assertVarDefined(self, doc: FakeDocument, var_mark: int, ref_marks: list[int]):
        var_node = doc.node_at(doc.start_of(var_mark))
        self.assertIsInstance(var_node, Id.Var)

        loader = self.workspace(doc, "file:///tmp")
        def_provider = DefinitionProvider(loader)

        for ref_mark in ref_marks:
            self.assertSequenceEqual(
                def_provider.serve(doc.ast, doc.start_of(ref_mark)),
                [var_node.location],
            )

    def assertParamDefined(
        self,
        loader: DocumentLoader,
        params: list[AST],
        refs: list[AST],
    ):
        def_provider = DefinitionProvider(loader)
        param_locations = [param.to(Id.Var).location for param in params]

        for ref in refs:
            ref_location = ref.to(Id.ParamRef).location
            tree = must(loader.get(ref_location.uri))
            self.assertSequenceEqual(
                def_provider.serve(tree, ref_location.range.start),
                param_locations,
            )

    def assertFieldDefined(
        self,
        loader: DocumentLoader,
        keys: list[AST],
        refs: list[AST],
    ):
        def_provider = DefinitionProvider(loader)
        key_locations = [key.to(Id.Field).location for key in keys]

        for ref in refs:
            ref_location = ref.to(Id.FieldRef).location
            tree = must(loader.get(ref_location.uri))
            self.assertSequenceEqual(
                def_provider.serve(tree, ref_location.range.start),
                key_locations,
            )


class TestVarDefinition(TestDefinition):
    def setUp(self) -> None:
        self.setUpPyfakefs()

    def test_assert_expr(self):
        self.assertVarDefined(
            FakeDocument(
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
            FakeDocument(
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
            FakeDocument(
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
        t = FakeDocument(
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
        t = FakeDocument(
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
        t = FakeDocument(
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
        t = FakeDocument(
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
        t = FakeDocument(
            dedent(
                """\
                local f = 'f'; local v = { f: 0 }; v[f]
                      ^1             ^2            ^3^4
                """
            )
        )

        self.assertVarDefined(t, var_mark=1, ref_marks=[4])
        self.assertVarDefined(t, var_mark=2, ref_marks=[3])


class TestParamDefinition(TestDefinition):
    def setUp(self) -> None:
        self.setUpPyfakefs()

    def test_local_fn(self):
        t = FakeDocument(
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
        t = FakeDocument(
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
        t = FakeDocument(
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
        t1 = FakeDocument(
            dedent(
                """\
                function(p) = p + 1
                         ^1
                """
            ),
            uri="file:///tmp/doc1.jsonnet",
        )

        t2 = FakeDocument(
            dedent(
                """\
                local f = import 'doc1.jsonnet';
                f(p=1)
                  ^1
                """
            ),
            uri="file:///tmp/doc2.jsonnet",
        )

        self.assertParamDefined(
            self.workspace(
                docs=[t1, t2],
                root_uri="file:///tmp",
            ),
            params=[t1 @ 1],
            refs=[t2 @ 1],
        )


class TestFieldDefinition(TestDefinition):
    def setUp(self) -> None:
        self.setUpPyfakefs()

    def test_local(self):
        t = FakeDocument(
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
        t = FakeDocument(
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
        t = FakeDocument(
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
        t = FakeDocument(
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
        t = FakeDocument(
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
        t = FakeDocument(
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
                { f: 2 }
                  ^1
                """
            ),
            uri="file:///tmp/doc2.jsonnet",
        )

        t3 = FakeDocument(
            dedent(
                """\
                if true
                then import "doc1.jsonnet"
                else import "doc2.jsonnet"
                """
            ),
            uri="file:///tmp/doc3.jsonnet",
        )

        t4 = FakeDocument(
            dedent(
                """\
                (import "doc3.jsonnet").f
                                        ^1
                """
            ),
            uri="file:///tmp/doc4.jsonnet",
        )

        self.assertFieldDefined(
            self.workspace(
                docs=[t1, t2, t3, t4],
                root_uri="file:///tmp",
            ),
            keys=[t1 @ 1, t2 @ 1],
            refs=[t4 @ 1],
        )

    def test_self(self):
        t = FakeDocument(
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
        t = FakeDocument(
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
        t = FakeDocument(
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


class TestParamFieldDefinition(TestDefinition):
    def test_literal_arg(self):
        t = FakeDocument(
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
        t = FakeDocument(
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
        t1 = FakeDocument(
            dedent(
                """\
                function(p) p.f
                              ^1
                """
            ),
            uri="file:///tmp/doc1.jsonnet",
        )

        t2 = FakeDocument(
            dedent(
                """\
                local f = import 'doc1.jsonnet';
                f({ f: 2 })
                    ^1
                """
            ),
            uri="file:///tmp/doc2.jsonnet",
        )

        self.assertFieldDefined(
            self.workspace(
                docs=[t1, t2],
                root_uri="file:///tmp",
            ),
            keys=[t2 @ 1],
            refs=[t1 @ 1],
        )

    def test_imported_fn_param_default(self):
        t1 = FakeDocument(
            dedent(
                """\
                function(p={ f: 1 }) p.f
                             ^1        ^2
                """
            ),
            uri="file:///tmp/doc1.jsonnet",
        )

        t2 = FakeDocument(
            dedent(
                """\
                local f = import 'doc1.jsonnet';
                f({ f: 2 })
                    ^1
                """
            ),
            uri="file:///tmp/doc2.jsonnet",
        )

        self.assertFieldDefined(
            self.workspace(
                docs=[t1, t2],
                root_uri="file:///tmp",
            ),
            keys=[t1 @ 1, t2 @ 1],
            refs=[t1 @ 2],
        )

    def test_param_default(self):
        t = FakeDocument(
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
        t = FakeDocument(
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
        t = FakeDocument(
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
        t = FakeDocument(
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

    def test_transitive_importers(self):
        t1 = FakeDocument("1", uri="file:///tmp/doc1.jsonnet")
        t2 = FakeDocument("import 'doc1.jsonnet'", uri="file:///tmp/doc2.jsonnet")
        t3 = FakeDocument("import 'doc2.jsonnet'", uri="file:///tmp/doc3.jsonnet")
        w = self.workspace([t1, t2, t3], root_uri="file:///tmp")

        self.assertSequenceEqual(
            sorted(
                w.transitive_importees(t3.ast),
                key=lambda doc: doc.location.uri,
            ),
            [t1.ast, t2.ast],
        )

        self.assertSequenceEqual(
            sorted(
                w.transitive_importers(t1.ast),
                key=lambda doc: doc.location.uri,
            ),
            [t2.ast, t3.ast],
        )
