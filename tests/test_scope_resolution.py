import unittest
from textwrap import dedent, indent

import lsprotocol.types as L

from joule.ast import (
    AST,
    Field,
    ListComp,
    Local,
    ObjComp,
    Object,
    Scope,
    Visibility,
    merge_locations,
)
from joule.util import head, maybe

from .dsl import FakeDocument, FieldBinding, VarBinding


class TestScopeResolution(unittest.TestCase):
    def checkBinding(
        self,
        scope: Scope,
        location: L.Location,
        name: str,
        bound_to: AST,
    ):
        def message():
            return "\n".join(
                [
                    "Binding not found:",
                    f"* Name: {name}",
                    f"* Location: {location}",
                    "* Bound to:",
                    indent(bound_to.pretty_tree, " " * 4),
                    "* With in:",
                    indent(scope.pretty_tree, " " * 4),
                ]
            )

        self.assertTrue(
            any(
                b.name == name and b.location == location and b.bound_to == bound_to
                for b in scope.bindings
            ),
            message(),
        )

    def assertVarsBound(self, owner: AST, bindings: VarBinding | list[VarBinding]):
        if isinstance(bindings, VarBinding):
            bindings = [bindings]

        self.assertTrue(owner.has_var_scope())

        scope = head(maybe(owner.var_scope))
        self.assertEqual(scope.owner.location, owner.location)

        for b in bindings:
            self.checkBinding(scope, b.location, b.name, b.bound_to)

    def checkFieldBindings(
        self,
        owner: Object,
        bindings: FieldBinding | list[FieldBinding],
    ):
        if isinstance(bindings, FieldBinding):
            bindings = [bindings]

        self.assertTrue(owner.has_field_scope())

        scope = head(maybe(owner.field_scope))
        self.assertEqual(scope.owner.location, owner.location)

        for b in bindings:
            self.checkBinding(
                scope,
                b.location,
                b.key.name,
                Field(
                    merge_locations(b.key, b.value),
                    b.key,
                    b.value,
                    b.visibility,
                    b.inherited,
                ),
            )

    def test_local(self):
        t = FakeDocument(
            dedent(
                """\
                local x = 1, x = 2; x + x
                ^0    ^1  ^2 ^3  ^4
                """
            )
        )

        self.assertVarsBound(
            t.node_at("0").to(Local),
            [
                t.var_binding(at="1", name="x", to=t.num(at="2", value=1)),
                t.var_binding(at="3", name="x", to=t.num(at="4", value=2)),
            ],
        )

    def test_object(self):
        t = FakeDocument(
            dedent(
                """\
                {
                    f1: v1,
                    ^^1 ^^2
                    "f2":: v2,
                    ^^^^3  ^^4
                    local v1 = 3,
                          ^^5  ^6
                    local v2 = 4,
                          ^^7  ^8
                }
                """
            )
        )

        obj = t.body.to(Object)

        self.checkFieldBindings(
            obj,
            [
                t.field_binding(
                    at="1",
                    key=t.fixed_id_key(at="1", name="f1"),
                    value=t.var_ref(at="2", name="v1"),
                ),
                t.field_binding(
                    at="3",
                    key=t.fixed_str_key(at="3", name="f2"),
                    value=t.var_ref(at="4", name="v2"),
                    visibility=Visibility.Hidden,
                ),
            ],
        )

        self.assertVarsBound(
            obj,
            [
                t.var_binding(at="5", name="v1", to=t.num(at="6", value=3)),
                t.var_binding(at="7", name="v2", to=t.num(at="8", value=4)),
            ],
        )

    def test_list_comp(self):
        t = FakeDocument(
            dedent(
                """\
                [
                    local x = 1;
                    ^1    ^2  ^3
                    x + i for i in [1, 2]
                              ^4   ^^^^^^5
                                    ^6 ^7
                ]
                """
            )
        )

        self.assertVarsBound(
            t.node_at("1").to(Local),
            t.var_binding(at="2", name="x", to=t.num(at="3", value=1)),
        )

        self.assertVarsBound(
            t.ast.body.to(ListComp),
            t.var_binding(
                at="4",
                name="i",
                to=t.array(
                    at="5",
                    values=[
                        t.num(at="6", value=1),
                        t.num(at="7", value=2),
                    ],
                ),
            ),
        )

    def test_obj_comp(self):
        t = FakeDocument(
            """\
            {
                local v1 = 1,
                      ^^1  ^2
                ['f' + i]: true,
                local v2 = 2,
                      ^^3  ^4
                for i in [3, 4]
                    ^5   ^^^^^^6
                          ^7 ^8
            }
            """
        )

        self.assertVarsBound(
            t.body.to(ObjComp),
            [
                t.var_binding(at="1", name="v1", to=t.num(at="2", value=1)),
                t.var_binding(at="3", name="v2", to=t.num(at="4", value=2)),
                t.var_binding(
                    at="5",
                    name="i",
                    to=t.array(
                        at="6",
                        values=[
                            t.num(at="7", value=3),
                            t.num(at="8", value=4),
                        ],
                    ),
                ),
            ],
        )
