from joule.maybe import just
from joule.syntax import trees as T
from joule.syntax.trees import BinaryOp as B
from tests import FakeDocumentTestCase


class TestScopeResolver(FakeDocumentTestCase):
    def assertVarBinding(self, owner: T.Tree, var: T.Id.Var, target: T.Tree):
        binding = var.binding
        self.assertIsNotNone(binding)

        binding = just(binding)
        self.assertEqual(owner, binding.scope.owner)
        self.assertEqual(binding.scope.get(var.name), binding)
        self.assertEqual(binding.target, target)

    def assertFieldBinding(self, owner: T.Object, field: T.Field):
        self.assertIsInstance(field.key, T.StaticKey)
        key = field.key.to(T.StaticKey)

        binding = key.id.binding
        self.assertIsNotNone(binding)

        binding = just(binding)
        self.assertEqual(owner, binding.scope.owner)
        self.assertEqual(binding.scope.get(key.id.name), binding)
        self.assertEqual(binding.target, field.value)

    def assertVarRef(self, var: T.Id.Var, *refs: T.Id.VarRef):
        self.assertIsNotNone(var.references)
        expected_refs = just(var.references)
        self.assertCountEqual(expected_refs, refs)

    def test_local(self):
        t = self.fake_document(
            """\
            :   local x = 1, y = 2; x + y
            >   ^1    ^2  ^3 ^4  ^5 ^6  ^7
            """
        )

        local = t.node_at(1).to(T.Local)

        x = t.var_at(2)
        x_val = t.num_at(3)
        x_ref = t.var_ref_at(6)

        self.assertVarBinding(local, x, x_val)
        self.assertVarRef(x, x_ref)

        y = t.var_at(4)
        y_val = t.num_at(5)
        y_ref = t.var_ref_at(7)

        self.assertVarBinding(local, y, y_val)
        self.assertVarRef(y, y_ref)

    def test_object_local(self):
        t = self.fake_document(
            """\
            :   { local x = 1, f: x + y, local y = 2 }
            >           ^1  ^2    ^3  ^4       ^5  ^6
            """
        )

        obj = t.body.to(T.Object)

        x = t.var_at(1)
        x_val = t.num_at(2)
        x_ref = t.var_ref_at(3)

        self.assertVarBinding(obj, x, x_val)
        self.assertVarRef(x, x_ref)

        y = t.var_at(5)
        y_val = t.num_at(6)
        y_ref = t.var_ref_at(4)

        self.assertVarBinding(obj, y, y_val)
        self.assertVarRef(y, y_ref)

    def test_multi_var_refs(self):
        t = self.fake_document(
            """\
            :   local x = 1; x + x
            >         ^1  ^2 ^3  ^4
            """
        )

        local = t.body.to(T.Local)
        x = t.var_at(1)
        x_val = t.num_at(2)
        x_ref1 = t.var_ref_at(3)
        x_ref2 = t.var_ref_at(4)

        self.assertVarBinding(local, x, x_val)
        self.assertVarRef(x, x_ref1, x_ref2)

    def test_nested_local(self):
        t = self.fake_document(
            """\
            :   local x = 1; local y = 2; x + y
            >   ^1    ^2  ^3 ^4    ^5  ^6 ^7  ^8
            """
        )

        outer_local = t.node_at(1).to(T.Local)
        inner_local = t.node_at(4).to(T.Local)

        x = t.var_at(2)
        x_val = t.num_at(3)
        x_ref = t.var_ref_at(7)

        self.assertVarBinding(outer_local, x, x_val)
        self.assertVarRef(x, x_ref)

        y = t.var_at(5)
        y_val = t.num_at(6)
        y_ref = t.var_ref_at(8)

        self.assertVarBinding(inner_local, y, y_val)
        self.assertVarRef(y, y_ref)

    def test_shadowed_var(self):
        t = self.fake_document(
            """\
            :   local x = 1; local x = 2, y = 3; { f: x + y, local y = 4 }
            >                ^1    ^2  ^3        ^4   ^5  ^6       ^7  ^8
            """
        )

        local = t.node_at(1).to(T.Local)
        obj = t.node_at(4).to(T.Object)

        x = t.var_at(2)
        x_val = t.num_at(3)
        x_ref = t.var_ref_at(5)

        self.assertVarBinding(local, x, x_val)
        self.assertVarRef(x, x_ref)

        y = t.var_at(7)
        y_val = t.num_at(8)
        y_ref = t.var_ref_at(6)

        self.assertVarBinding(obj, y, y_val)
        self.assertVarRef(y, y_ref)

    def test_object(self):
        t = self.fake_document(
            """\
            :   { f1: v1, "f2":: v2, local v1 = 3, local v2 = 4 }
            >       ^1^2      ^3 ^4        ^5   ^6       ^7   ^8
            """
        )

        obj = t.body.to(T.Object)

        f1 = t.node_at(1).to(T.Field)
        f2 = t.node_at(3).to(T.Field)

        self.assertFieldBinding(obj, field=f1)
        self.assertFieldBinding(obj, field=f2)

        v1 = t.var_at(5)
        v1_val = t.num_at(6)
        v1_ref = t.var_ref_at(2)

        self.assertVarBinding(obj, v1, v1_val)
        self.assertVarRef(v1, v1_ref)

        v2 = t.var_at(7)
        v2_val = t.num_at(8)
        v2_ref = t.var_ref_at(4)

        self.assertVarBinding(obj, v2, v2_val)
        self.assertVarRef(v2, v2_ref)

    def test_fn(self):
        t = self.fake_document(
            """\
            :   function(a = 1, b = a) local c = a + b; c
            >            ^1  ^2 ^3  ^4 ^5    ^6  ^7  ^8 ^9
            """
        )

        fn = t.body.to(T.Fn)

        a = t.var_at(1)
        a_param = t.node_at(1, 2).to(T.Param)
        a_ref1 = t.var_ref_at(4)
        a_ref2 = t.var_ref_at(7)

        self.assertVarBinding(fn, a, a_param)
        self.assertVarRef(a, a_ref1, a_ref2)

        b = t.var_at(3)
        b_param = t.node_at(3, 4).to(T.Param)
        b_ref = t.var_ref_at(8)

        self.assertVarBinding(fn, b, b_param)
        self.assertVarRef(b, b_ref)

        local = t.node_at(5).to(T.Local)

        c = t.var_at(6)
        c_val = B.Plus(a_ref2, b_ref)
        c_ref = t.var_ref_at(9)

        self.assertVarBinding(local, c, c_val)
        self.assertVarRef(c, c_ref)

    def test_field_fn(self):
        t = self.fake_document(
            """\
            :   { f(p): p }
            >      ^^^^^^1
            >       ^2  ^3
            """
        )

        p = t.var_at(2)
        p_param = just(p.parent).to(T.Param)
        p_ref = t.var_ref_at(3)

        self.assertVarBinding(t.node_at(1).to(T.Fn), p, p_param)
        self.assertVarRef(p, p_ref)

    def test_array_comp(self):
        t = self.fake_document(
            """\
            :   [ local x = 1; x + k for k in ks ]
            >     ^1    ^2  ^3 ^4  ^5^6  ^7
            """
        )

        local = t.node_at(1).to(T.Local)
        x = t.var_at(2)
        x_val = t.num_at(3)

        self.assertVarBinding(local, x, x_val)

        spec = t.node_at(6).to(T.ForSpec)
        k = t.var_at(7)
        x_ref = t.var_ref_at(4)
        k_ref = t.var_ref_at(5)

        self.assertVarBinding(spec, k, spec)
        self.assertVarRef(k, k_ref)
        self.assertVarRef(x, x_ref)

    def test_obj_comp(self):
        t = self.fake_document(
            """\
            :   { local v1 = 1, ['f' + k]: v1 + v2 + k, local v2 = 2, for k in ks }
            >           ^1   ^2        ^3  ^4   ^5   ^6       ^7   ^8 ^9  ^10
            """
        )

        obj_comp = t.body.to(T.ObjComp)

        v1 = t.var_at(1)
        v1_val = t.num_at(2)
        v1_ref = t.var_ref_at(4)

        self.assertVarBinding(obj_comp, v1, v1_val)
        self.assertVarRef(v1, v1_ref)

        v2 = t.var_at(7)
        v2_val = t.num_at(8)
        v2_ref = t.var_ref_at(5)

        self.assertVarBinding(obj_comp, v2, v2_val)
        self.assertVarRef(v2, v2_ref)

        for_spec = t.node_at(9).to(T.ForSpec)

        k = t.var_at(10)
        k_ref1 = t.var_ref_at(3)
        k_ref2 = t.var_ref_at(6)

        self.assertVarBinding(for_spec, k, for_spec)
        self.assertVarRef(k, k_ref1, k_ref2)
