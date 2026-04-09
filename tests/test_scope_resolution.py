import unittest
from textwrap import dedent

from joule import ast as A
from joule.maybe import must

from .dsl import FakeDocument, param


class TestScopeResolution(unittest.TestCase):
    def assertVarBinding(self, owner: A.AST, var: A.Id.Var, target: A.AST):
        binding = var.binding
        self.assertIsNotNone(binding)

        binding = must(binding)
        self.assertEqual(owner, binding.scope.owner)
        self.assertEqual(binding.scope.get(var.name), binding)
        self.assertEqual(binding.target, target)

    def assertFieldBinding(self, owner: A.Object, field: A.Field):
        self.assertIsInstance(field.key, A.FixedKey)
        key = field.key.to(A.FixedKey)

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
            owner=t.node_at(1).to(A.Local),
            var=t.node_at(2).to(A.Id.Var),
            target=t.node_at(3).to(A.Num),
        )

        self.assertVarBinding(
            owner=t.node_at(1).to(A.Local),
            var=t.node_at(4).to(A.Id.Var),
            target=t.node_at(5).to(A.Num),
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

        obj = t.body.to(A.Object)

        self.assertFieldBinding(
            owner=obj,
            field=t.node_at(1).to(A.Field),
        )

        self.assertFieldBinding(
            owner=obj,
            field=t.node_at(2).to(A.Field),
        )

        self.assertVarBinding(
            owner=obj,
            var=t.node_at(3).to(A.Id.Var),
            target=t.node_at(4).to(A.Num),
        )

        self.assertVarBinding(
            owner=obj,
            var=t.node_at(5).to(A.Id.Var),
            target=t.node_at(6).to(A.Num),
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
            owner=t.node_at(1).to(A.Local),
            var=t.node_at(2).to(A.Id.Var),
            target=t.node_at(3).to(A.Num),
        )

        self.assertVarBinding(
            owner=t.node_at(4).to(A.ForSpec),
            var=t.node_at(5).to(A.Id.Var),
            target=t.node_at(4).to(A.ForSpec),
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
            owner=t.body.to(A.ObjComp),
            var=t.node_at(1).to(A.Id.Var),
            target=t.node_at(2).to(A.Num),
        )

        self.assertVarBinding(
            owner=t.body.to(A.ObjComp),
            var=t.node_at(3).to(A.Id.Var),
            target=t.node_at(4).to(A.Num),
        )

        self.assertVarBinding(
            owner=t.node_at(5),
            var=t.node_at(6).to(A.Id.Var),
            target=t.node_at(5).to(A.ForSpec),
        )

    def test_field_fn_params(self):
        t = FakeDocument(
            """\
            { f(p): p }
               ^^^^^^1
                ^2
            """
        )

        self.assertVarBinding(
            owner=t.node_at(1).to(A.Fn),
            var=t.node_at(2).to(A.Id.Var),
            target=param(A.Id.Var(t.at(2), "p")),
        )
