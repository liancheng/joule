import joule.trees as T
from joule.maybe import must
from tests import FakeDocumentTestCase


class TestAnalyzer(FakeDocumentTestCase):
    def assertVarBinding(self, owner: T.Tree, var: T.Id.Var, target: T.Tree):
        binding = var.binding
        self.assertIsNotNone(binding)

        binding = must(binding)
        self.assertEqual(owner, binding.scope.owner)
        self.assertEqual(binding.scope.get(var.name), binding)
        self.assertEqual(binding.target, target)

    def assertFieldBinding(self, owner: T.Object, field: T.Field):
        self.assertIsInstance(field.key, T.FixedKey)
        key = field.key.to(T.FixedKey)

        binding = key.id.binding
        self.assertIsNotNone(binding)

        binding = must(binding)
        self.assertEqual(owner, binding.scope.owner)
        self.assertEqual(binding.scope.get(key.id.name), binding)
        self.assertEqual(binding.target, field)

    def test_local(self):
        t = self.fake_document(
            """\
            local x = 1, y = 2; x + y
            ^1    ^2  ^3 ^4  ^5
            """
        )

        self.assertVarBinding(
            owner=t.node_at(1).to(T.Local),
            var=t.node_at(2).to(T.Id.Var),
            target=t.node_at(3).to(T.Num),
        )

        self.assertVarBinding(
            owner=t.node_at(1).to(T.Local),
            var=t.node_at(4).to(T.Id.Var),
            target=t.node_at(5).to(T.Num),
        )

    def test_object(self):
        t = self.fake_document(
            """\
            {
                f1: v1,
            |   ^^^^^^1
                "f2":: v2,
            |   ^^^^^^^^^2
                local v1 = 3,
            |         ^3   ^4
                local v2 = 4,
            |         ^5   ^6
            }
            """
        )

        obj = t.body.to(T.Object)

        self.assertFieldBinding(
            owner=obj,
            field=t.node_at(1).to(T.Field),
        )

        self.assertFieldBinding(
            owner=obj,
            field=t.node_at(2).to(T.Field),
        )

        self.assertVarBinding(
            owner=obj,
            var=t.node_at(3).to(T.Id.Var),
            target=t.node_at(4).to(T.Num),
        )

        self.assertVarBinding(
            owner=obj,
            var=t.node_at(5).to(T.Id.Var),
            target=t.node_at(6).to(T.Num),
        )

    def test_list_comp(self):
        t = self.fake_document(
            """\
            [
                local x = 1;
            |   ^1    ^2  ^3
                x + i for i in [1, 2]
            |         ^4: ^5        ^:4
            ]
            """
        )

        self.assertVarBinding(
            owner=t.node_at(1).to(T.Local),
            var=t.node_at(2).to(T.Id.Var),
            target=t.node_at(3).to(T.Num),
        )

        self.assertVarBinding(
            owner=t.node_at(4).to(T.ForSpec),
            var=t.node_at(5).to(T.Id.Var),
            target=t.node_at(4).to(T.ForSpec),
        )

    def test_obj_comp(self):
        t = self.fake_document(
            """\
            {
                local v1 = 1,
            |         ^1   ^2
                ['f' + i]: true,
                local v2 = 2,
            |         ^3   ^4
                for i in [3, 4]
            |   ^5: ^6        ^:5
            }
            """
        )

        self.assertVarBinding(
            owner=t.body.to(T.ObjComp),
            var=t.node_at(1).to(T.Id.Var),
            target=t.at(2).num(1),
        )

        self.assertVarBinding(
            owner=t.body.to(T.ObjComp),
            var=t.node_at(3).to(T.Id.Var),
            target=t.at(4).num(2),
        )

        self.assertVarBinding(
            owner=t.node_at(5),
            var=t.node_at(6).to(T.Id.Var),
            target=t.node_at(5).to(T.ForSpec),
        )

    def test_field_fn_params(self):
        t = self.fake_document(
            """\
            { f(p): p }
            |  ^^^^^^1
            |   ^2
            """
        )

        self.assertVarBinding(
            owner=t.node_at(1).to(T.Fn),
            var=t.node_at(2).to(T.Id.Var),
            target=must(t.node_at(2).parent).to(T.Param),
        )

    def test_imports(self):
        t = self.fake_document(
            """\
            local f1 = import "f1.jsonnet";
            |                 ^^^^^^^^^^^^1
            local f2 = import "f2.jsonnet";
            |                 ^^^^^^^^^^^^2
            null
            """
        )

        self.assertSequenceEqual(
            t.document.importees,
            [
                T.Importee.from_string(t.at(1).str("f1.jsonnet")),
                T.Importee.from_string(t.at(2).str("f2.jsonnet")),
            ],
        )
