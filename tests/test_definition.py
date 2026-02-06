import unittest
from textwrap import dedent, indent

from rich.console import Console
from rich.text import Text

from joule.ast import AST, Id, Object, Scope
from joule.providers import DefinitionProvider
from joule.util import head, maybe

from .dsl import FakeDocument


class TestDefinition(unittest.TestCase):
    def report(self, doc: FakeDocument, scope: Scope, defn: AST, ref: AST) -> str:
        console = Console()
        with console.capture() as capture:
            console.print(Text("Variable not defined:"))
            console.print(
                Text(", ").join(
                    [
                        Text(" Scope ", "black on yellow"),
                        Text(" Variable ", "black on red"),
                        Text(" Reference ", "black on blue"),
                    ]
                ),
            )
            console.print(
                doc.highlight(
                    [
                        (scope.owner.location.range, "black on yellow"),
                        (defn.location.range, "black on red"),
                        (ref.location.range, "black on blue"),
                    ]
                ),
            )
            console.print("\nScope:\n")
            console.print(indent(scope.pretty_tree, " " * 4))
            console.print("\nScope owner AST:\n")
            console.print(indent(scope.owner.pretty_tree, " " * 4))

        return capture.get()

    def assertVarDefined(
        self,
        doc: FakeDocument,
        var_mark: str,
        ref_marks: str | list[str],
    ):
        if isinstance(ref_marks, str):
            ref_marks = [ref_marks]

        provider = DefinitionProvider(doc.ast)

        for ref_mark in ref_marks:
            var = doc.node_at(var_mark).to(Id.Var)
            var_ref = doc.node_at(ref_mark).to(Id.VarRef)

            self.assertSequenceEqual(
                provider.serve(doc.start_of(ref_mark)),
                [var.location],
                self.report(doc, head(maybe(var.bound_in)), var, var_ref),
            )

    def assertFieldDefined(
        self,
        doc: FakeDocument,
        obj_mark: str,
        key_mark: str,
        ref_marks: str | list[str],
    ):
        if isinstance(ref_marks, str):
            ref_marks = [ref_marks]

        provider = DefinitionProvider(doc.ast)
        obj = doc.node_at(obj_mark).to(Object)

        for ref_mark in ref_marks:
            key = doc.node_at(key_mark).to(Id.Field)
            field_scope = head(maybe(obj.field_scope))
            ref = doc.node_at(ref_mark).to(Id.FieldRef)

            self.assertSequenceEqual(
                provider.serve(doc.start_of(ref_mark)),
                [key.location],
                self.report(doc, field_scope, key, ref),
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

        self.assertVarDefined(t, var_mark="1", ref_marks="2")

    def test_local_shadowing(self):
        t = FakeDocument(
            dedent(
                """\
                local x = 1;
                local x = 2;
                      ^1
                x
                ^2
                """
            )
        )

        self.assertVarDefined(t, var_mark="1", ref_marks="2")

    def test_fn_params(self):
        t = FakeDocument(
            dedent(
                """
                function(p1=p2, p2, p3=p1)
                         ^1 ^2  ^3  ^4 ^5
                    p1 + p2 + p3
                    ^6   ^7   ^8
                """
            )
        )

        self.assertVarDefined(t, var_mark="1", ref_marks=["5", "6"])
        self.assertVarDefined(t, var_mark="3", ref_marks=["2", "7"])
        self.assertVarDefined(t, var_mark="4", ref_marks=["8"])

    def test_list_comp(self):
        t = FakeDocument(
            dedent(
                """\
                [
                    local v = 0;
                          ^1
                    i + v for i in [2, 3]
                    ^2  ^3    ^4
                ]
                """
            )
        )

        self.assertVarDefined(t, var_mark="1", ref_marks="3")
        self.assertVarDefined(t, var_mark="4", ref_marks="2")

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

        self.assertVarDefined(t, var_mark="1", ref_marks="4")
        self.assertVarDefined(t, var_mark="2", ref_marks="5")
        self.assertVarDefined(t, var_mark="6", ref_marks="3")

    def test_field_access(self):
        t = FakeDocument(
            dedent(
                """\
                local v = { f: 1 };
                      ^1
                v.f
                ^2
                """
            )
        )

        self.assertVarDefined(t, var_mark="1", ref_marks="2")

    def test_slice_var_index(self):
        t = FakeDocument(
            dedent(
                """\
                local f = 'f';
                      ^1
                local v = { f: 0 };
                      ^2
                v[f]
                ^3^4
                """
            )
        )

        self.assertVarDefined(t, var_mark="1", ref_marks="4")
        self.assertVarDefined(t, var_mark="2", ref_marks="3")

    def test_field(self):
        t = FakeDocument(
            dedent(
                """\
                local v = { f: 0 };
                          ^1^2
                v.f
                  ^3
                """
            )
        )

        self.assertFieldDefined(t, obj_mark="1", key_mark="2", ref_marks="3")

    def test_nested_field(self):
        t = FakeDocument(
            dedent(
                """\
                local v = { f: { g: 0 } };
                      ^1  ^2^3   ^4
                v.f.g
                ^5^6^7
                """
            )
        )

        self.assertVarDefined(t, var_mark="1", ref_marks="5")
        self.assertFieldDefined(t, obj_mark="2", key_mark="3", ref_marks="6")
        self.assertFieldDefined(t, obj_mark="2", key_mark="4", ref_marks="7")
