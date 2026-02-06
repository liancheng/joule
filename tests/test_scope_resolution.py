import unittest
from textwrap import dedent, indent

import lsprotocol.types as L

from joule.ast import (
    AST,
    Field,
    FixedKey,
    ForSpec,
    Id,
    Local,
    Num,
    ObjComp,
    Object,
    Scope,
)
from joule.util import head, maybe

from .dsl import FakeDocument, VarBinding


class TestScopeResolution(unittest.TestCase):
    def assertBinding(
        self,
        scope: Scope,
        location: L.Location,
        name: str,
        to: AST,
    ):
        def message():
            return "\n".join(
                [
                    "Binding not found:",
                    f"* Name: {name}",
                    f"* Location: {location}",
                    "* Bound to:",
                    indent(to.pretty_tree, " " * 4),
                    "* With in:",
                    indent(scope.pretty_tree, " " * 4),
                ]
            )

        self.assertTrue(
            any(
                b.name == name and b.location == location and b.target == to
                for b in scope.bindings
            ),
            message(),
        )

    def assertVarBindings(self, owner: AST, bindings: VarBinding | list[VarBinding]):
        if isinstance(bindings, tuple):
            bindings = [bindings]

        for var, to in bindings:
            scope = head(maybe(var.bound_in))
            self.assertEqual(scope.owner, owner)
            self.assertBinding(scope, var.location, var.name, to)

    def assertFieldBindings(self, owner: Object, fields: Field | list[Field]):
        if isinstance(fields, Field):
            fields = [fields]

        scope = head(maybe(owner.field_scope))
        self.assertEqual(scope.owner, owner)

        for f in fields:
            self.assertBinding(scope, f.key.location, f.key.to(FixedKey).name, f)

    def test_local(self):
        t = FakeDocument(
            dedent(
                """\
                local x = 1, x = 2; x + x
                ^0    ^1  ^2 ^3  ^4
                """
            )
        )

        self.assertVarBindings(
            t.node_at("0").to(Local),
            [
                (t.node_at("1").to(Id.Var), t.node_at("2").to(Num)),
                (t.node_at("3").to(Id.Var), t.node_at("4").to(Num)),
            ],
        )

    def test_object(self):
        t = FakeDocument(
            dedent(
                """\
                {
                    f1: v1,
                    ^^^^^^1
                    "f2":: v2,
                    ^^^^^^^^^2
                    local v1 = 3,
                          ^3   ^4
                    local v2 = 4,
                          ^5   ^6
                }
                """
            )
        )

        obj = t.body.to(Object)

        self.assertFieldBindings(
            obj,
            [
                t.node_at("1").to(Field),
                t.node_at("2").to(Field),
            ],
        )

        self.assertVarBindings(
            obj,
            [
                (t.node_at("3").to(Id.Var), t.node_at("4").to(Num)),
                (t.node_at("5").to(Id.Var), t.node_at("6").to(Num)),
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
                          ^4: ^5        ^:4
                ]
                """
            )
        )

        self.assertVarBindings(
            t.node_at("1").to(Local),
            (t.node_at("2").to(Id.Var), t.node_at("3").to(Num)),
        )

        self.assertVarBindings(
            t.node_at("4").to(ForSpec),
            (t.node_at("5").to(Id.Var), t.node_at("4").to(ForSpec)),
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
                ^5: ^6        ^:5
            }
            """
        )

        self.assertVarBindings(
            t.body.to(ObjComp),
            [
                (t.node_at("1").to(Id.Var), t.node_at("2").to(Num)),
                (t.node_at("3").to(Id.Var), t.node_at("4").to(Num)),
            ],
        )

        self.assertVarBindings(
            t.node_at("5"),
            (t.node_at("6").to(Id.Var), t.node_at("5").to(ForSpec)),
        )
