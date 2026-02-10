import unittest
from textwrap import dedent, indent

from rich.console import Console
from rich.text import Text

from joule.ast import AST, Id, Scope
from joule.providers import DefinitionProvider
from joule.util import head, maybe

from .dsl import FakeDocument


class TestDefinition(unittest.TestCase):
    def dump_definitions(
        self,
        doc: FakeDocument,
        scopes: Scope | list[Scope],
        defs: AST | list[AST],
        ref: AST,
    ) -> str:
        if isinstance(scopes, Scope):
            scopes = [scopes]

        if isinstance(defs, AST):
            defs = [defs]

        console = Console()
        scope_style = "black on yellow"
        def_style = "black on red"
        ref_style = "black on blue"

        with console.capture() as capture:
            console.print(Text("Variable not defined:"))
            console.print(
                Text(", ").join(
                    [
                        Text(" scope ", scope_style),
                        Text(" definition ", def_style),
                        Text(" reference ", ref_style),
                    ]
                ),
            )

            console.print(
                doc.highlight(
                    [(scope.owner.location.range, scope_style) for scope in scopes]
                    + [(ref.location.range, ref_style)]
                    + [(d.location.range, def_style) for d in defs]
                ),
            )

            for scope in scopes:
                console.print("\nScope:\n")
                console.print(indent(scope.pretty_tree, " " * 4))
                console.print("\nScope owner AST:\n")
                console.print(indent(scope.owner.pretty_tree, " " * 4))

        return capture.get()

    def dump_var_definition(self, doc: FakeDocument, var: Id.Var, ref: Id.VarRef):
        return self.dump_definitions(doc, head(maybe(var.bound_in)), var, ref)

    def dump_field_definitions(
        self,
        doc: FakeDocument,
        keys: AST | list[AST],
        ref: Id.FieldRef,
    ):
        if isinstance(keys, AST):
            keys = [keys]

        scopes = [scope for key in keys for scope in maybe(key.to(Id.Field).bound_in)]

        return self.dump_definitions(doc, scopes, keys, ref)

    def assertVarDefined(
        self,
        doc: FakeDocument,
        var_mark: int,
        ref_marks: int | list[int],
    ):
        if isinstance(ref_marks, int):
            ref_marks = [ref_marks]

        provider = DefinitionProvider(doc.ast)

        for ref_mark in ref_marks:
            var = doc.node_at(var_mark).to(Id.Var)
            var_ref = doc.node_at(ref_mark).to(Id.VarRef)

            self.assertSequenceEqual(
                provider.serve(doc.start_of(ref_mark)),
                [var.location],
                self.dump_var_definition(doc, var, var_ref),
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

        provider = DefinitionProvider(doc.ast)

        for ref_mark in ref_marks:
            keys = [doc.node_at(mark) for mark in key_marks]
            ref = doc.node_at(ref_mark).to(Id.FieldRef)

            self.assertSequenceEqual(
                provider.serve(doc.start_of(ref_mark)),
                [key.location for key in keys],
                self.dump_field_definitions(doc, keys, ref),
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

    def test_field_access(self):
        t = FakeDocument(
            dedent(
                """\
                local v = { f: 1 }; v.f
                      ^1            ^2
                """
            )
        )

        self.assertVarDefined(t, var_mark=1, ref_marks=2)

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
                            ^1        ^2
                """
            )
        )

        self.assertFieldDefined(t, key_marks=1, ref_marks=2)

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
