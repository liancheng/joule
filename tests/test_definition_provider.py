import lsprotocol.types as L

from joule.features import DefinitionProvider
from joule.syntax import trees as T
from joule.workspace import FolderIndex
from tests import FakeWorkspaceTestCase
from tests.dsl import FakeDocument


class TestDefinitionProvider(FakeWorkspaceTestCase):
    def assertVarDefined(
        self,
        index: FolderIndex,
        doc: FakeDocument,
        var: T.Id.Var,
        *points: T.Point,
    ):
        __tracebackhide__ = True

        provider = DefinitionProvider(index)

        for point in points:
            obtained = provider.serve(doc.document, point.to_position())
            expected = [L.Location(doc.uri, var.span.to_range())]
            self.assertCountEqual(obtained, expected)

    def assertFieldDefined(
        self,
        index: FolderIndex,
        doc: FakeDocument,
        fields: T.Id.Field | list[T.Id.Field],
        *points: T.Point,
    ):
        __tracebackhide__ = True

        fields = [fields] if isinstance(fields, T.Id.Field) else fields
        provider = DefinitionProvider(index)

        for point in points:
            obtained = provider.serve(doc.document, point.to_position())
            expected = [L.Location(doc.uri, f.span.to_range()) for f in fields]
            self.assertCountEqual(obtained, expected)

    def test_local(self):
        index = self.index_workspace(
            t := self.fake_document(
                "f.jsonnet",
                """\
                :   local x = 1, y = x + 1; x + y
                >         ^1     ^2  ^3     ^4  ^5
                """,
            )
        )

        x = t.var_at(1)
        y = t.var_at(2)

        self.assertVarDefined(index, t, x, t.at(3).end, t.at(4).end)
        self.assertVarDefined(index, t, y, t.at(5).end)

    def test_field(self):
        index = self.index_workspace(
            t := self.fake_document(
                "f.jsonnet",
                """\
                :   local obj = { f: 1 }; obj.f
                >                 ^1          ^2
                """,
            )
        )

        f = t.node_at(1).to(T.Id.Field)
        self.assertFieldDefined(index, t, f, t.at(2).end)

    def test_nested_field(self):
        index = self.index_workspace(
            t := self.fake_document(
                "f.jsonnet",
                """\
                :   local obj = { f1: { f2: 1 } }; obj.f1.f2
                >                       ^^1               ^^2
                """,
            )
        )

        f2 = t.node_at(1).to(T.Id.Field)
        self.assertFieldDefined(index, t, f2, t.at(2).end)

    def test_field_in_nested_local(self):
        index = self.index_workspace(
            t := self.fake_document(
                "f.jsonnet",
                """\
                :   local obj1 = local obj2 = { f: 1 }; obj2; obj1.f
                >                               ^1                 ^2
                """,
            )
        )

        f = t.node_at(1).to(T.Id.Field)
        self.assertFieldDefined(index, t, f, t.at(2).end)

    def test_returned_field(self):
        index = self.index_workspace(
            t := self.fake_document(
                "f.jsonnet",
                """\
                :   local fn(p) = { f: p }; fn(1).f
                >                   ^1            ^2
                """,
            )
        )

        f = t.node_at(1).to(T.Id.Field)
        self.assertFieldDefined(index, t, f, t.at(2).end)

    def test_field_multi_defs(self):
        index = self.index_workspace(
            t := self.fake_document(
                "f.jsonnet",
                """\
                :   local obj = if true then { f: 1 } else { f: 2 }; obj.f
                >                              ^1            ^2          ^3
                """,
            )
        )

        f1 = t.node_at(1).to(T.Id.Field)
        f2 = t.node_at(2).to(T.Id.Field)

        self.assertFieldDefined(index, t, [f1, f2], t.at(3).end)
