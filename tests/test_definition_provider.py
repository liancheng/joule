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

        self.assertVarReferenced(
            t.var_at(1),
            t.var_ref_at(2),
        )

    def test_object_local_var(self):
        t = self.fake_document(
            """\
            :   {
            :       local x = 1,
            >             ^1
            :       f: x + x,
            >          ^2  ^3
            :   }
            """
        )

        self.assertVarReferenced(
            t.var_at(1),
            t.var_ref_at(2),
            t.var_ref_at(3),
        )

    def test_shadowed_var(self):
        t = self.fake_document(
            """\
            :   local x = 1; x = 2; x
            >                ^1     ^2
            """
        )

        self.assertVarReferenced(
            t.var_at(1),
            t.var_ref_at(2),
        )
