from joule import trees as T
from joule.maybe import just
from tests import FakeDocumentTestCase


class TestDefinitionProvider(FakeDocumentTestCase):
    def assertVarReferenced(self, var: T.Id.Var, *refs: T.Id.VarRef):
        self.assertIsNotNone(var.references)
        self.assertCountEqual(just(var.references), refs)

    def test_local_var(self):
        t = self.fake_document(
            """\
            :   local x = 1; x
            >         ^1     ^2
            """
        )

        self.assertVarReferenced(t.var_at(1), t.var_ref_at(2))

    def test_object_local_var(self):
        t = self.fake_document(
            """\
            :   { local x = 1, f: x + y, local y = 2 }
            >           ^1        ^2  ^3       ^4
            """
        )

        self.assertVarReferenced(t.var_at(1), t.var_ref_at(2))
        self.assertVarReferenced(t.var_at(4), t.var_ref_at(3))

    def test_nested_vars(self):
        t = self.fake_document(
            """\
            :   local x = 1; local y = 2; x + y
            >         ^1           ^2     ^3  ^4
            """
        )

        self.assertVarReferenced(t.var_at(1), t.var_ref_at(3))
        self.assertVarReferenced(t.var_at(2), t.var_ref_at(4))

    def test_shadowed_var(self):
        t = self.fake_document(
            """\
            :   local x = 1; local x = 2, y = 3; { f: x + y, local y = 4 }
            >                      ^1                 ^2  ^3       ^4
            """
        )

        self.assertVarReferenced(t.var_at(1), t.var_ref_at(2))
        self.assertVarReferenced(t.var_at(4), t.var_ref_at(3))

    def test_multi_var_refs(self):
        t = self.fake_document(
            """\
            :   local x = 1; x + x
            >         ^1     ^2  ^3
            """
        )

        self.assertVarReferenced(t.var_at(1), t.var_ref_at(2), t.var_ref_at(3))

    def test_fn_param(self):
        t = self.fake_document(
            """\
            :   function(p1 = p3, p2 = p1, p3) p1 + p2 + p3
            >            ^1   ^2  ^3   ^4  ^5  ^6   ^7   ^8
            """
        )

        self.assertVarReferenced(t.var_at(1), t.var_ref_at(4), t.var_ref_at(6))
        self.assertVarReferenced(t.var_at(3), t.var_ref_at(7))
        self.assertVarReferenced(t.var_at(5), t.var_ref_at(2), t.var_ref_at(8))
