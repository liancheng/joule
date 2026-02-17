from contextlib import contextmanager
from typing import Callable, Sequence, cast

import lsprotocol.types as L

from joule.ast import (
    Bind,
    ComputedKey,
    Document,
    FixedKey,
    ForSpec,
    Object,
    Param,
)
from joule.visitor import Visitor


class DocumentSymbolProvider(Visitor):
    def __init__(self) -> None:
        self.root_symbol = L.DocumentSymbol(
            name="__root__",
            kind=L.SymbolKind.Module,
            range=L.Range(L.Position(0, 0), L.Position(0, 0)),
            selection_range=L.Range(L.Position(0, 0), L.Position(0, 0)),
        )
        self.breadcrumb = [self.root_symbol]

    def serve(self, tree: Document) -> Sequence[L.DocumentSymbol]:
        self.visit(tree)
        return self.root_symbol.children or []

    def add_symbol(self, symbol: L.DocumentSymbol):
        parent = self.breadcrumb[-1]
        children = cast(list, parent.children) or []
        children.append(symbol)
        parent.children = children

    @contextmanager
    def open_symbol(self, symbol: L.DocumentSymbol):
        self.breadcrumb.append(symbol)
        try:
            yield symbol
        finally:
            self.breadcrumb.pop()

    def visit_bind(self, b: Bind):
        symbol = L.DocumentSymbol(
            name=b.id.name,
            kind=L.SymbolKind.Variable,
            range=b.id.location.range,
            selection_range=b.location.range,
        )

        self.add_symbol(symbol)
        with self.open_symbol(symbol):
            self.visit(b.value)

    def visit_param(self, p: Param):
        symbol = L.DocumentSymbol(
            name=p.id.name,
            kind=L.SymbolKind.Variable,
            range=p.id.location.range,
            selection_range=p.location.range,
        )

        self.add_symbol(symbol)

        if p.default is not None:
            with self.open_symbol(symbol):
                self.visit(p.default)

    def visit_object(self, e: Object):
        for f in e.fields:
            match f.key:
                case FixedKey() as k:
                    symbol = L.DocumentSymbol(
                        name=k.id.name,
                        kind=L.SymbolKind.Field,
                        range=k.location.range,
                        selection_range=f.location.range,
                    )

                    self.add_symbol(symbol)
                    with self.open_symbol(symbol):
                        self.visit_field_value(f)

                case ComputedKey() as k:
                    self.visit_computed_key(f, k)
                    self.visit_field_value(f)

        for b in e.binds:
            self.visit_bind(b)

        for a in e.assertions:
            self.visit_assert(a)

    def visit_for_spec(self, s: ForSpec, next: Callable[[], None]):
        def new_next():
            symbol = L.DocumentSymbol(
                name=s.id.name,
                kind=L.SymbolKind.Variable,
                range=s.id.location.range,
                selection_range=s.location.range,
            )

            self.add_symbol(symbol)
            next()

        super().visit_for_spec(s, new_next)
