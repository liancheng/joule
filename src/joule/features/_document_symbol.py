from collections.abc import Callable, Sequence
from contextlib import contextmanager
from typing import override

import lsprotocol.types as L

from joule.maybe import maybe
from joule.syntax import trees as T
from joule.syntax.visitor import Visitor


class DocumentSymbolProvider(Visitor):
    doc: T.Document
    root_symbol: L.DocumentSymbol
    breadcrumb: list[L.DocumentSymbol]

    def __init__(self, doc: T.Document):
        self.doc = doc

        dummy_range = L.Range(
            L.Position(0, 0),
            L.Position(0, 0),
        )

        self.root_symbol = L.DocumentSymbol(
            name="__root__",
            kind=L.SymbolKind.Module,
            range=dummy_range,
            selection_range=dummy_range,
        )

        self.breadcrumb = [self.root_symbol]

    def serve(self) -> Sequence[L.DocumentSymbol]:
        self.visit(self.doc)
        return self.root_symbol.children or []

    def add_symbol(self, symbol: L.DocumentSymbol):
        parent = self.breadcrumb[-1]
        children = [child for children in maybe(parent.children) for child in children]
        children.append(symbol)
        parent.children = children

    @contextmanager
    def activate(self, symbol: L.DocumentSymbol):
        self.breadcrumb.append(symbol)
        try:
            yield symbol
        finally:
            self.breadcrumb.pop()

    @override
    def visit_bind(self, t: T.Bind):
        kind = (
            L.SymbolKind.Function
            if isinstance(t.value, T.Fn)
            else L.SymbolKind.Variable
        )

        symbol = L.DocumentSymbol(
            name=t.id.name,
            kind=kind,
            range=t.id.span.to_range(),
            selection_range=t.span.to_range(),
        )

        self.add_symbol(symbol)

        with self.activate(symbol):
            self.visit(t.value)

    @override
    def visit_param(self, t: T.Param):
        symbol = L.DocumentSymbol(
            name=t.id.name,
            kind=L.SymbolKind.Variable,
            range=t.id.span.to_range(),
            selection_range=t.span.to_range(),
        )

        self.add_symbol(symbol)

        if t.default is not None:
            with self.activate(symbol):
                self.visit(t.default)

    @override
    def visit_object(self, t: T.Object):
        for f in t.fields:
            match f.key:
                case T.StaticKey() as k:
                    symbol = L.DocumentSymbol(
                        name=k.id.name,
                        kind=L.SymbolKind.Field,
                        range=k.span.to_range(),
                        selection_range=f.span.to_range(),
                    )

                    self.add_symbol(symbol)
                    with self.activate(symbol):
                        self.visit_field_value(f)

                case T.ComputedKey() as k:
                    self.visit_computed_key(f, k)
                    self.visit_field_value(f)

        for b in t.binds:
            self.visit_bind(b)

        for a in t.asserts:
            self.visit_assert(a)

    def visit_for_spec(self, t: T.ForSpec, next: Callable[[], None]):
        def new_next():
            symbol = L.DocumentSymbol(
                name=t.id.name,
                kind=L.SymbolKind.Variable,
                range=t.id.span.to_range(),
                selection_range=t.span.to_range(),
            )

            self.add_symbol(symbol)
            next()

        super().visit_for_spec(t, new_next)
