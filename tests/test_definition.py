import unittest
from textwrap import dedent

from joule.ast import Id
from joule.model.document_loader import DocumentLoader
from joule.providers import DefinitionProvider
from tests.dsl.fake_document import fake_workspace

from .dsl import FakeDocument


class TestDefinition(unittest.TestCase):
    def assertVarDefined(self, doc: FakeDocument, var: int, refs: list[int]):
        var_node = doc.node_at(doc.start_of(var))
        assert var_node.is_a(Id.Var)

        loader = fake_workspace([doc], "file:///tmp")
        provider = DefinitionProvider(loader)

        for ref_mark in refs:
            self.assertSequenceEqual(
                provider.serve(doc.ast, doc.start_of(ref_mark)),
                [var_node.location],
            )

    def assertParamDefined(
        self,
        loader: DocumentLoader,
        params: list[Id.Var],
        refs: list[Id.ParamRef],
    ):
        provider = DefinitionProvider(loader)
        param_locations = [param.location for param in params]

        for ref in refs:
            tree = loader.get_or_load(ref.location.uri)
            self.assertSequenceEqual(
                provider.serve(tree, ref.location.range.start),
                param_locations,
            )

    def assertFieldDefined(
        self,
        loader: DocumentLoader,
        keys: list[Id.Field],
        refs: list[Id.FieldRef],
    ):
        provider = DefinitionProvider(loader)

        for ref in refs:
            tree = loader.get_or_load(ref.location.uri)
            self.assertSequenceEqual(
                provider.serve(tree, ref.location.range.start),
                [key.location for key in keys],
            )

    def test_local(self):
        t = FakeDocument(
            dedent(
                """\
                local x = 1; x
                      ^1     ^2
                """
            )
        )

        self.assertVarDefined(t, var=1, refs=[2])

    def test_local_shadowing(self):
        t = FakeDocument(
            dedent(
                """\
                local x = 1; local x = 2; x
                                   ^1     ^2
                """
            )
        )

        self.assertVarDefined(t, var=1, refs=[2])

    def test_fn_params(self):
        t = FakeDocument(
            dedent(
                """
                function(p1=p2, p2, p3=p1) p1 + p2 + p3
                         ^1 ^2  ^3  ^4 ^5  ^6   ^7   ^8
                """
            )
        )

        self.assertVarDefined(t, var=1, refs=[5, 6])
        self.assertVarDefined(t, var=3, refs=[2, 7])
        self.assertVarDefined(t, var=4, refs=[8])

    def test_field_fn_params(self):
        t = FakeDocument(
            dedent(
                """\
                { f(p1=p2, p2, p3=p1): p1 + p2 + p3 }
                    ^1 ^2  ^3  ^4 ^5   ^6   ^7   ^8
                """
            )
        )

        self.assertVarDefined(t, var=1, refs=[5, 6])
        self.assertVarDefined(t, var=3, refs=[2, 7])
        self.assertVarDefined(t, var=4, refs=[8])

    def test_list_comp(self):
        t = FakeDocument(
            dedent(
                """\
                [local v = 0; i + v for i in [2, 3]]
                       ^1     ^2  ^3    ^4
                """
            )
        )

        self.assertVarDefined(t, var=1, refs=[3])
        self.assertVarDefined(t, var=4, refs=[2])

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

        self.assertVarDefined(t, var=1, refs=[4])
        self.assertVarDefined(t, var=2, refs=[5])
        self.assertVarDefined(t, var=6, refs=[3])

    def test_slice_var_index(self):
        t = FakeDocument(
            dedent(
                """\
                local f = 'f'; local v = { f: 0 }; v[f]
                      ^1             ^2            ^3^4
                """
            )
        )

        self.assertVarDefined(t, var=1, refs=[4])
        self.assertVarDefined(t, var=2, refs=[3])

    def test_field(self):
        t = FakeDocument(
            dedent(
                """\
                local v = { f: 0 }; v.f
                      ^1    ^2      ^3^4
                """
            )
        )

        self.assertVarDefined(t, var=1, refs=[3])
        self.assertFieldDefined(
            fake_workspace([t]),
            keys=[t.node_at(2).to(Id.Field)],
            refs=[t.node_at(4).to(Id.FieldRef)],
        )

    def test_nested_field(self):
        t = FakeDocument(
            dedent(
                """\
                local v = { f: { g: 0 } }; v.f.g
                      ^1    ^2   ^3        ^4^5^6
                """
            )
        )

        self.assertVarDefined(t, var=1, refs=[4])

        self.assertFieldDefined(
            fake_workspace([t]),
            keys=[t.node_at(2).to(Id.Field)],
            refs=[t.node_at(5).to(Id.FieldRef)],
        )

        self.assertFieldDefined(
            fake_workspace([t]),
            keys=[t.node_at(3).to(Id.Field)],
            refs=[t.node_at(6).to(Id.FieldRef)],
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
            fake_workspace([t]),
            keys=[t.node_at(2).to(Id.Field)],
            refs=[t.node_at(1).to(Id.FieldRef)],
        )

    def test_if(self):
        t = FakeDocument(
            dedent(
                """\
                local v = if true then { f: 1 } else { f: 2 }; v.f
                                         ^1            ^2        ^3
                """
            )
        )

        self.assertFieldDefined(
            fake_workspace([t]),
            keys=[
                t.node_at(1).to(Id.Field),
                t.node_at(2).to(Id.Field),
            ],
            refs=[t.node_at(3).to(Id.FieldRef)],
        )

    def test_if_no_alternative(self):
        t = FakeDocument(
            dedent(
                """\
                local v = if true then { f: 1 }; v.f
                                         ^1        ^2
                """
            )
        )

        self.assertFieldDefined(
            fake_workspace([t]),
            keys=[t.node_at(1).to(Id.Field)],
            refs=[t.node_at(2).to(Id.FieldRef)],
        )

    def test_if_with_var_refs(self):
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
            fake_workspace([t]),
            keys=[
                t.node_at(1).to(Id.Field),
                t.node_at(2).to(Id.Field),
            ],
            refs=[t.node_at(3).to(Id.FieldRef)],
        )

    def test_call(self):
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
            fake_workspace([t]),
            params=[t.node_at(1).to(Id.Var)],
            refs=[t.node_at(2).to(Id.ParamRef)],
        )

    def test_call_field_fn(self):
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
            fake_workspace([t]),
            params=[t.node_at(1).to(Id.Var)],
            refs=[t.node_at(2).to(Id.ParamRef)],
        )

    def test_call_field_fn_with_if(self):
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
            fake_workspace([t]),
            params=[
                t.node_at(1).to(Id.Var),
                t.node_at(2).to(Id.Var),
            ],
            refs=[t.node_at(3).to(Id.ParamRef)],
        )

    @unittest.skip("TODO")
    def test_field_of_call_arg(self):
        t = FakeDocument(
            dedent(
                """\
                local v = { f: 1 };
                            ^1
                local f(p) = p.f;
                               ^2
                f(v);
                """
            )
        )

        self.assertParamDefined(
            fake_workspace([t]),
            params=[t.node_at(1).to(Id.Var)],
            refs=[t.node_at(2).to(Id.ParamRef)],
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
                local v = import "doc3.jsonnet";
                v.f
                  ^1
                """
            ),
            uri="file:///tmp/doc4.jsonnet",
        )

        self.assertFieldDefined(
            fake_workspace([t1, t2, t3, t4], root_uri="file:///tmp"),
            keys=[
                t1.node_at(1).to(Id.Field),
                t2.node_at(1).to(Id.Field),
            ],
            refs=[t4.node_at(1).to(Id.FieldRef)],
        )

    def test_self(self):
        t = FakeDocument(
            """\
            { local root = self, f(p): p, g: root.f(1) }
                                 ^1               ^2
            """
        )

        self.assertFieldDefined(
            fake_workspace([t]),
            keys=[t.node_at(1).to(Id.Field)],
            refs=[t.node_at(2).to(Id.FieldRef)],
        )
