from collections.abc import Sequence

import lsprotocol.types as L
from lsprotocol.types import SymbolKind as K

from joule import trees as T
from joule.providers import DocumentSymbolProvider
from tests import FakeDocumentTestCase
from tests.dsl import FakeDocument


def symbol(
    name: str,
    kind: L.SymbolKind,
    span: T.Span,
    selection_span: T.Span | None = None,
    children: list[L.DocumentSymbol] | None = None,
) -> L.DocumentSymbol:
    if selection_span is None:
        selection_span = span

    return L.DocumentSymbol(
        name=name,
        kind=kind,
        range=span.to_range(),
        selection_range=selection_span.to_range(),
        children=children,
    )


def symbols_in(doc: FakeDocument) -> Sequence[L.DocumentSymbol]:
    return DocumentSymbolProvider(doc.document).serve()


class TestDocumentSymbolProvider(FakeDocumentTestCase):
    def test_local(self):
        t = self.fake_document(
            """\
            :   local x = 0, y = 1; x + y
            >         ^1  ^2 ^3  ^4
            """
        )

        x = symbol("x", K.Variable, t.at(1), t.at(1, 2))
        y = symbol("y", K.Variable, t.at(3), t.at(3, 4))

        self.assertEqual(symbols_in(t), [x, y])

    def test_nested_local(self):
        t = self.fake_document(
            """\
            :   local x = 0; local y = 1; x + y
            >         ^1  ^2       ^3  ^4
            """
        )

        x = symbol("x", K.Variable, t.at(1), t.at(1, 2))
        y = symbol("y", K.Variable, t.at(3), t.at(3, 4))

        self.assertEqual(symbols_in(t), [x, y])

    def test_local_fn(self):
        t = self.fake_document(
            """\
            :   local func(p, q = 1) = p * 2; func(1)
            >         ^^^^1^2 ^3  ^4       ^5
            """
        )

        p = symbol("p", K.Variable, t.at(2), t.at(2))
        q = symbol("q", K.Variable, t.at(3), t.at(3, 4))
        func = symbol("func", K.Function, t.at(1), t.at(1, 5), [p, q])

        self.assertEqual(symbols_in(t), [func])

    def test_object_fields(self):
        t = self.fake_document(
            """\
            :   { a: { b: 1, c: 2 } }
            >     ^1   ^2 ^3 ^4 ^5^6
            """
        )

        b = symbol("b", K.Field, t.at(2), t.at(2, 3))
        c = symbol("c", K.Field, t.at(4), t.at(4, 5))
        a = symbol("a", K.Field, t.at(1), t.at(1, 6), [b, c])

        self.assertEqual(symbols_in(t), [a])
