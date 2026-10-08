import lsprotocol.types as L

from joule import trees as T
from joule.providers import DefinitionProvider
from tests import FakeDocumentTestCase
from tests.dsl import FakeDocument


class TestDefinitionProvider(FakeDocumentTestCase):
    def assertDefined(self, doc: FakeDocument, var: T.Id.Var, *points: T.Point):
        provider = DefinitionProvider(doc.uri, doc.document)

        for point in points:
            obtained = provider.serve(point.to_position())
            expected = [L.Location(doc.uri, var.span.to_range())]
            self.assertCountEqual(obtained, expected)

    def test_local(self):
        t = self.fake_document(
            """\
            :   local x = 1, y = x + 1; x + y
            >         ^1     ^2  ^3     ^4  ^5
            """
        )

        x = t.var_at(1)
        y = t.var_at(2)

        self.assertDefined(t, x, t.at(3).end, t.at(4).end)
        self.assertDefined(t, y, t.at(5).end)
