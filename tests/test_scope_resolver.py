from joule import trees as T
from joule.maybe import just
from joule.trees import BinaryOp as B
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
        for ref in refs:
            self.assertEqual(ref.var, var)
            self.assertIn(ref, var.references)

        self.assertEqual(len(var.references), len(refs))

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

        self.assertVarBinding(owner=local, var=x, target=x_val)
        self.assertVarRef(x, x_ref)

        y = t.var_at(4)
        y_val = t.num_at(5)
        y_ref = t.var_ref_at(7)

        self.assertVarBinding(owner=local, var=y, target=y_val)
        self.assertVarRef(y, y_ref)

    def test_object(self):
        t = self.fake_document(
            """\
            :   {
            :       f1: v1,
            >         ^1^2
            :       "f2":: v2,
            >           ^3 ^4
            :       local v1 = 3,
            >             ^5   ^6
            :       local v2 = 4,
            >             ^7   ^8
            :   }
            """
        )

        obj = t.body.to(T.Object)

        f1 = t.node_at(1).to(T.Field)
        f2 = t.node_at(3).to(T.Field)

        self.assertFieldBinding(owner=obj, field=f1)
        self.assertFieldBinding(owner=obj, field=f2)

        v1 = t.var_at(5)
        v1_val = t.num_at(6)
        v1_ref = t.var_ref_at(2)

        self.assertVarBinding(owner=obj, var=v1, target=v1_val)
        self.assertVarRef(v1, v1_ref)

        v2 = t.var_at(7)
        v2_val = t.num_at(8)
        v2_ref = t.var_ref_at(4)

        self.assertVarBinding(owner=obj, var=v2, target=v2_val)
        self.assertVarRef(v2, v2_ref)

    def test_fn(self):
        t = self.fake_document(
            """\
            :   function(a = 1, b = a)
            >            ^1  ^2 ^3  ^4
            :       local c = a + b;
            >       ^5    ^6  ^7  ^8
            :       c
            >       ^9
            """
        )

        fn = t.body.to(T.Fn)

        a = t.var_at(1)
        a_param = t.node_at(1, 2).to(T.Param)
        a_ref1 = t.var_ref_at(4)
        a_ref2 = t.var_ref_at(7)

        self.assertVarBinding(owner=fn, var=a, target=a_param)
        self.assertVarRef(a, a_ref1, a_ref2)

        b = t.var_at(3)
        b_param = t.node_at(3, 4).to(T.Param)
        b_ref = t.var_ref_at(8)

        self.assertVarBinding(owner=fn, var=b, target=b_param)
        self.assertVarRef(b, b_ref)

        local = t.node_at(5).to(T.Local)

        c = t.var_at(6)
        c_val = B.Plus(a_ref2, b_ref)
        c_ref = t.var_ref_at(9)

        self.assertVarBinding(owner=local, var=c, target=c_val)
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

        self.assertVarBinding(owner=t.node_at(1).to(T.Fn), var=p, target=p_param)
        self.assertVarRef(p, p_ref)

    def test_array_comp(self):
        t = self.fake_document(
            """\
            :   [
            :       local x = 1;
            >       ^1    ^2  ^3
            :       x + k for k in ks
            >       ^4  ^5^6  ^7
            :   ]
            """
        )

        local = t.node_at(1).to(T.Local)
        x = t.var_at(2)
        x_val = t.num_at(3)

        self.assertVarBinding(owner=local, var=x, target=x_val)

        spec = t.node_at(6).to(T.ForSpec)
        k = t.var_at(7)
        x_ref = t.var_ref_at(4)
        k_ref = t.var_ref_at(5)

        self.assertVarBinding(owner=spec, var=k, target=spec)
        self.assertVarRef(k, k_ref)
        self.assertVarRef(x, x_ref)

    def test_obj_comp(self):
        t = self.fake_document(
            """\
            :   {
            :       local v1 = 1,
            >             ^1   ^2
            :       ['f' + k]: v1 + v2 + k,
            >              ^3  ^4   ^5   ^6
            :       local v2 = 2,
            >             ^7   ^8
            :       for k in ks
            >       ^9  ^10
            :   }
            """
        )

        obj_comp = t.body.to(T.ObjComp)

        v1 = t.var_at(1)
        v1_val = t.num_at(2)
        v1_ref = t.var_ref_at(4)

        self.assertVarBinding(owner=obj_comp, var=v1, target=v1_val)
        self.assertVarRef(v1, v1_ref)

        v2 = t.var_at(7)
        v2_val = t.num_at(8)
        v2_ref = t.var_ref_at(5)

        self.assertVarBinding(owner=obj_comp, var=v2, target=v2_val)
        self.assertVarRef(v2, v2_ref)

        for_spec = t.node_at(9).to(T.ForSpec)

        k = t.var_at(10)
        k_ref1 = t.var_ref_at(3)
        k_ref2 = t.var_ref_at(6)

        self.assertVarBinding(owner=for_spec, var=k, target=for_spec)
        self.assertVarRef(k, k_ref1, k_ref2)
