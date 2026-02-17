import unittest
from textwrap import dedent

from joule.ast import Id
from joule.providers import DefinitionProvider
from tests.dsl.fake_document import fake_workspace

from .dsl import FakeDocument


class TestDefinition(unittest.TestCase):
    def assertVarDefined(
        self,
        doc: FakeDocument,
        var_mark: int,
        ref_marks: int | list[int],
    ):
        if isinstance(ref_marks, int):
            ref_marks = [ref_marks]

        loader = fake_workspace("file:///tmp", [doc])
        provider = DefinitionProvider(loader)

        for ref_mark in ref_marks:
            var = doc.node_at(var_mark).to(Id.Var)
            self.assertSequenceEqual(
                provider.serve(doc.ast, doc.start_of(ref_mark)),
                [var.location],
            )

    def assertParamDefined(
        self,
        doc: FakeDocument,
        param_mark: int,
        ref_marks: int | list[int],
    ):
        if isinstance(ref_marks, int):
            ref_marks = [ref_marks]

        loader = fake_workspace("file:///tmp", [doc])
        provider = DefinitionProvider(loader)

        for ref_mark in ref_marks:
            var = doc.node_at(param_mark).to(Id.Var)
            self.assertSequenceEqual(
                provider.serve(doc.ast, doc.start_of(ref_mark)),
                [var.location],
            )

    def assertFieldDefined(
        self,
        doc: FakeDocument,
        key_marks: int | list[int],
        ref_marks: int | list[int],
    ):
        if isinstance(key_marks, int):
            key_marks = [key_marks]

        if isinstance(ref_marks, int):
            ref_marks = [ref_marks]

        loader = fake_workspace("file:///tmp", [doc])
        provider = DefinitionProvider(loader)

        for ref_mark in ref_marks:
            keys = [doc.node_at(mark) for mark in key_marks]
            self.assertSequenceEqual(
                provider.serve(doc.ast, doc.start_of(ref_mark)),
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

        self.assertVarDefined(t, var_mark=1, ref_marks=2)

    def test_local_shadowing(self):
        t = FakeDocument(
            dedent(
                """\
                local x = 1; local x = 2; x
                                   ^1     ^2
                """
            )
        )

        self.assertVarDefined(t, var_mark=1, ref_marks=2)

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

    def test_list_comp(self):
        t = FakeDocument(
            dedent(
                """\
                [local v = 0; i + v for i in [2, 3]]
                       ^1     ^2  ^3    ^4
                """
            )
        )

        self.assertVarDefined(t, var_mark=1, ref_marks=3)
        self.assertVarDefined(t, var_mark=4, ref_marks=2)

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

        self.assertVarDefined(t, var_mark=1, ref_marks=4)
        self.assertVarDefined(t, var_mark=2, ref_marks=5)
        self.assertVarDefined(t, var_mark=6, ref_marks=3)

    def test_slice_var_index(self):
        t = FakeDocument(
            dedent(
                """\
                local f = 'f'; local v = { f: 0 }; v[f]
                      ^1             ^2            ^3^4
                """
            )
        )

        self.assertVarDefined(t, var_mark=1, ref_marks=4)
        self.assertVarDefined(t, var_mark=2, ref_marks=3)

    def test_field(self):
        t = FakeDocument(
            dedent(
                """\
                local v = { f: 0 }; v.f
                      ^1    ^2      ^3^4
                """
            )
        )

        self.assertVarDefined(t, var_mark=1, ref_marks=3)
        self.assertFieldDefined(t, key_marks=2, ref_marks=4)

    def test_nested_field(self):
        t = FakeDocument(
            dedent(
                """\
                local v = { f: { g: 0 } }; v.f.g
                      ^1    ^2   ^3        ^4^5^6
                """
            )
        )

        self.assertVarDefined(t, var_mark=1, ref_marks=4)
        self.assertFieldDefined(t, key_marks=2, ref_marks=5)
        self.assertFieldDefined(t, key_marks=3, ref_marks=6)

    def test_dollar(self):
        t = FakeDocument(
            dedent(
                """\
                { f: 1, g: { h: $.i, i: 2 }, i: 3 }
                                  ^1         ^2
                """
            )
        )

        self.assertFieldDefined(t, key_marks=2, ref_marks=1)

    def test_if(self):
        t = FakeDocument(
            dedent(
                """\
                local v = if true then { f: 1 } else { f: 2 }; v.f
                                         ^1            ^2        ^3
                """
            )
        )

        self.assertFieldDefined(t, key_marks=[1, 2], ref_marks=3)

    def test_if_no_alternative(self):
        t = FakeDocument(
            dedent(
                """\
                local v = if true then { f: 1 }; v.f
                                         ^1        ^2
                """
            )
        )

        self.assertFieldDefined(t, key_marks=1, ref_marks=2)

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

        self.assertFieldDefined(t, key_marks=[1, 2], ref_marks=3)

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

        self.assertParamDefined(t, param_mark=1, ref_marks=2)

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

        self.assertParamDefined(t, param_mark=1, ref_marks=2)

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

        self.assertFieldDefined(t, key_marks=1, ref_marks=2)

    def test_import(self):
        t1 = FakeDocument(
            dedent(
                """\
                if true then { f: 1 } else { f: 2 }
                               ^1            ^2
                """
            ),
            uri="file:///tmp/doc1.jsonnet",
        )

        t2 = FakeDocument(
            dedent(
                """\
                local v = import "doc1.jsonnet";
                v.f
                  ^1
                """
            ),
            uri="file:///tmp/doc2.jsonnet",
        )

        loader = fake_workspace(
            root_uri="file:///tmp",
            fakes=[t1, t2],
        )

        provider = DefinitionProvider(loader)
        self.assertSequenceEqual(
            provider.serve(t2.ast, t2.start_of(1)),
            [t1.at(1), t1.at(2)],
        )
