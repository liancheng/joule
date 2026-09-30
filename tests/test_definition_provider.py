from joule.services.definition_provider import DefinitionProvider
from tests import FakeDocumentTestCase
from tests.dsl import FakeDocument


class TestDefinitionProvider(FakeDocumentTestCase):
    def assertVarDefined(self, doc: FakeDocument, var_mark: int, ref_marks: list[int]):
        var = doc.var_at(var_mark)
        def_provider = DefinitionProvider(doc.document)

        for ref_mark in ref_marks:
            ref = doc.var_ref_at(ref_mark)
            self.assertSetEqual(set(def_provider.find_definition(ref)), {var.span})

    def test_local(self):
        t = self.fake_document(
            """\
            :   local x = 1; x
            >         ^1     ^2
            """
        )

        self.assertVarDefined(t, var_mark=1, ref_marks=[2])
