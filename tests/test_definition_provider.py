import lsprotocol.types as L

from joule.features import DefinitionProvider
from joule.syntax import trees as T
from tests import FakeDocumentTestCase
from tests.dsl import FakeDocument


class TestDefinitionProvider(FakeDocumentTestCase):
    def assertVarDefined(self, doc: FakeDocument, var: T.Id.Var, *points: T.Point):
        __tracebackhide__ = True

        provider = DefinitionProvider(doc.uri, doc.document)

        for point in points:
            obtained = provider.serve(point.to_position())
            expected = [L.Location(doc.uri, var.span.to_range())]
            self.assertCountEqual(obtained, expected)

    def assertFieldDefined(
        self,
        doc: FakeDocument,
        fields: T.Id.Field | list[T.Id.Field],
        *points: T.Point,
    ):
        __tracebackhide__ = True

        fields = [fields] if isinstance(fields, T.Id.Field) else fields
        provider = DefinitionProvider(doc.uri, doc.document)

        for point in points:
            obtained = provider.serve(point.to_position())
            expected = [L.Location(doc.uri, f.span.to_range()) for f in fields]
            self.assertCountEqual(obtained, expected)

    def test_local(self):
        t = self.fake_document(
            """\
            :   local x = 1, y = x + 1; x + y
            >         ^1     ^2  ^3     ^4  ^5
            """
        )

        self.assertVarDefined(t, t.var_at(1), t.at(3).end, t.at(4).end)
        self.assertVarDefined(t, t.var_at(2), t.at(5).end)

    def test_field(self):
        t = self.fake_document(
            """\
            :   local obj = { f: 1 }; obj.f
            >                 ^1          ^2
            """
        )

        self.assertFieldDefined(t, t.node_at(1).to(T.Id.Field), t.at(2).end)

    def test_nested_field(self):
        t = self.fake_document(
            """\
            :   local obj = { f1: { f2: 1 } }; obj.f1.f2
            >                       ^^1               ^^2
            """
        )

        self.assertFieldDefined(t, t.node_at(1).to(T.Id.Field), t.at(2).end)

    def test_field_in_nested_local(self):
        t = self.fake_document(
            """\
            :   local obj1 = local obj2 = { f: 1 }; obj2; obj1.f
            >                               ^1                 ^2
            """
        )

        self.assertFieldDefined(t, t.node_at(1).to(T.Id.Field), t.at(2).end)

    def test_returned_field(self):
        t = self.fake_document(
            """\
            :   local fn(p) = { f: p }; fn(1).f
            >                   ^1            ^2
            """
        )

        self.assertFieldDefined(t, t.node_at(1).to(T.Id.Field), t.at(2).end)

    def test_field_multi_defs(self):
        t = self.fake_document(
            """\
            :   local obj = if true then { f: 1 } else { f: 2 }; obj.f
            >                              ^1            ^2          ^3
            """
        )

        f1 = t.node_at(1).to(T.Id.Field)
        f2 = t.node_at(2).to(T.Id.Field)

        self.assertFieldDefined(t, [f1, f2], t.at(3).end)
