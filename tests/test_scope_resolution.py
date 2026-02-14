import unittest
from textwrap import dedent

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
)
from joule.maybe import must

from .dsl import FakeDocument


class TestScopeResolution(unittest.TestCase):
    def assertVarBinding(self, owner: AST, var: Id.Var, target: AST):
        binding = var.binding
        self.assertIsNotNone(binding)

        binding = must(binding)
        self.assertEqual(owner, binding.scope.owner)
        self.assertEqual(binding.scope.get(var.name), binding)
        self.assertEqual(binding.target, target)

    def assertFieldBinding(self, owner: Object, field: Field):
        self.assertTrue(field.key.is_a(FixedKey))
        key = field.key.to(FixedKey)

        binding = key.id.binding
        self.assertIsNotNone(binding)

        binding = must(binding)
        self.assertEqual(owner, binding.scope.owner)
        self.assertEqual(binding.scope.get(key.id.name), binding)
        self.assertEqual(binding.target, field)

    def test_local(self):
        t = FakeDocument(
            dedent(
                """\
                local x = 1, y = 2; x + y
                ^1    ^2  ^3 ^4  ^5
                """
            )
        )

        self.assertVarBinding(
            t.node_at(1).to(Local),
            t.node_at(2).to(Id.Var),
            t.node_at(3).to(Num),
        )

        self.assertVarBinding(
            t.node_at(1).to(Local),
            t.node_at(4).to(Id.Var),
            t.node_at(5).to(Num),
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

        self.assertFieldBinding(obj, t.node_at(1).to(Field))
        self.assertFieldBinding(obj, t.node_at(2).to(Field))

        self.assertVarBinding(
            obj,
            t.node_at(3).to(Id.Var),
            t.node_at(4).to(Num),
        )

        self.assertVarBinding(
            obj,
            t.node_at(5).to(Id.Var),
            t.node_at(6).to(Num),
        )

    def test_list_comp(self):
        t = FakeDocument(
            dedent(
                """\
                [
                    local x = 1;
                    ^1    ^2  ^3
                    x + i for i in [1, 2]
                          ^4: ^5        ^:
                ]
                """
            )
        )

        self.assertVarBinding(
            t.node_at(1).to(Local),
            t.node_at(2).to(Id.Var),
            t.node_at(3).to(Num),
        )

        self.assertVarBinding(
            t.node_at(4).to(ForSpec),
            t.node_at(5).to(Id.Var),
            t.node_at(4).to(ForSpec),
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
                ^5: ^6        ^:
            }
            """
        )

        self.assertVarBinding(
            t.body.to(ObjComp),
            t.node_at(1).to(Id.Var),
            t.node_at(2).to(Num),
        )

        self.assertVarBinding(
            t.body.to(ObjComp),
            t.node_at(3).to(Id.Var),
            t.node_at(4).to(Num),
        )

        self.assertVarBinding(
            t.node_at(5),
            t.node_at(6).to(Id.Var),
            t.node_at(5).to(ForSpec),
        )
