from joule.maybe import just
from joule.services.definition_provider import DefinitionProvider
from tests import FakeDocumentTestCase
from tests.dsl import FakeDocument


class TestDefinitionProvider(FakeDocumentTestCase):
    def assertVarDefined(self, doc: FakeDocument, var_mark: int, ref_marks: list[int]):
        def_provider = DefinitionProvider(doc.document)
        var = doc.var_at(var_mark)
        expected_refs = [doc.var_ref_at(mark) for mark in ref_marks]
        obtained_refs = just(var.references)

        for ref in expected_refs:
            found_def_spans = def_provider.find_definition(ref)
            self.assertSetEqual(set(found_def_spans), {var.span})

        self.assertSetEqual(set(obtained_refs), set(expected_refs))

    def test_local(self):
        t = self.fake_document(
            """\
            :   local x = 1; x
            >         ^1     ^2
            """
        )

        self.assertVarDefined(t, var_mark=1, ref_marks=[2])

    def test_object_local(self):
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

        self.assertVarDefined(t, var_mark=1, ref_marks=[2, 3])
