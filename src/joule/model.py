import dataclasses as D
from collections import defaultdict
from contextlib import contextmanager
from itertools import chain
from pathlib import Path
from typing import Sequence

import lsprotocol.types as L

from joule.ast import (
    AST,
    Binary,
    Bind,
    Binding,
    Document,
    Expr,
    Field,
    FieldAccess,
    FixedKey,
    Fn,
    ForSpec,
    Id,
    Import,
    Local,
    Object,
    Operator,
    Scope,
    Self,
    Str,
    Super,
    Visibility,
)
from joule.icon import Icon
from joule.parsing import parse_jsonnet
from joule.typing import URI
from joule.util import head_or_none, maybe
from joule.visitor import Visitor


@D.dataclass(frozen=True)
class PositionKey:
    pos: L.Position

    def __hash__(self) -> int:
        return hash((self.pos.line, self.pos.character))


@D.dataclass(frozen=True)
class LocationKey:
    location: L.Location

    def __hash__(self) -> int:
        return hash(
            (
                self.location.uri,
                self.location.range.start.line,
                self.location.range.start.character,
                self.location.range.end.line,
                self.location.range.end.character,
            )
        )


class DocumentIndex(Visitor):
    def __init__(self, workspace_index: "WorkspaceIndex", doc: Document) -> None:
        self.workspace_index = workspace_index
        self.doc: Document = doc
        self.inlay_hints: dict[PositionKey, L.InlayHint] = {}
        self.current_var_scope: Scope = Scope()
        self.current_self_scope: Scope | None = None
        self.current_super_scope: Scope | None = None
        self.root_symbol = L.DocumentSymbol(
            name="__root__",
            kind=L.SymbolKind.File,
            range=doc.location.range,
            selection_range=doc.location.range,
        )
        self.breadcrumbs = [self.root_symbol]
        self.ref_to_defs: LocationMap = defaultdict(list[L.Location])
        self.def_to_refs: LocationMap = defaultdict(list[L.Location])
        self.links: list[L.DocumentLink] = []
        self.hovers: dict[LocationKey, L.Hover] = {}

        self.visit(doc)

    @staticmethod
    def load(
        workspace: WorkspaceIndex,
        uri_or_path: URI | Path,
        source: str | None = None,
    ) -> DocumentIndex:
        match uri_or_path:
            case Path():
                path = uri_or_path
                uri = path.as_uri()
            case _:
                uri = uri_or_path
                path = Path.from_uri(uri)

        source = source or path.read_text("utf-8")
        cst = parse_jsonnet(source)
        doc = Document.from_cst(uri, cst)
        return DocumentIndex(workspace, doc)

    @property
    def uri(self):
        return self.doc.location.uri

    @property
    def document_symbols(self) -> Sequence[L.DocumentSymbol]:
        return self.root_symbol.children or []

    def add_document_symbol(self, symbol: L.DocumentSymbol):
        match (parent := self.breadcrumbs[-1]).children:
            case list() as children:
                children.append(symbol)
            case None:
                parent.children = [symbol]

    def definition(
        self,
        position: L.Position,
        include_current: bool = False,
        local: bool = False,
    ) -> list[L.Location]:
        return self.find_goto_locations(
            position, self.ref_to_defs, include_current, local
        )

    def references(
        self,
        position: L.Position,
        include_current: bool = False,
        local: bool = False,
    ) -> list[L.Location]:
        return self.find_goto_locations(
            position, self.def_to_refs, include_current, local
        )

    def find_goto_locations(
        self,
        position: L.Position,
        lookup: dict[LocationKey, list[L.Location]],
        include_current: bool = False,
        local: bool = False,
    ) -> list[L.Location]:
        for node in maybe(self.doc.node_at(position)):
            locations = iter(lookup[LocationKey(node.location)])

            if local:
                locations = filter(lambda x: x.uri == self.uri, locations)
            if include_current:
                locations = chain([node.location], locations)

            return list(locations)

        return []

    def add_reference(self, ref: Expr, binding: Binding):
        defs = self.ref_to_defs[LocationKey(ref.location)]
        refs = self.def_to_refs[LocationKey(binding.location)]

        defs.append(binding.location)
        refs.append(ref.location)

        ref_doc = (
            self
            if ref.location.uri == self.uri
            else self.workspace_index.get_or_load(ref.location.uri)
        )

        def_doc = (
            self
            if binding.location.uri == self.uri
            else self.workspace_index.get_or_load(binding.location.uri)
        )

        ref_doc.add_hint(
            L.InlayHint(
                position=ref.location.range.end,
                label=Icon.Reference,
            )
        )

        # Shows the # of references.
        def_doc.add_hint(
            L.InlayHint(
                position=binding.location.range.end,
                label=f"{Icon.Definition}{len(refs)}",
            )
        )

    def add_hint(self, hint: L.InlayHint):
        self.inlay_hints[PositionKey(hint.position)] = hint

    @contextmanager
    def parent_symbol(self, symbol: L.DocumentSymbol):
        self.breadcrumbs.append(symbol)
        try:
            yield symbol
        finally:
            self.breadcrumbs.pop()

    @contextmanager
    def var_scope(self, scope: Scope):
        prev = self.current_var_scope
        self.current_var_scope = scope
        try:
            yield self.current_var_scope
        finally:
            self.current_var_scope = prev

    @contextmanager
    def super_scope(self, scope: Scope | None):
        prev = self.current_super_scope
        self.current_super_scope = scope
        try:
            yield self.current_super_scope
        finally:
            self.current_super_scope = prev

    @contextmanager
    def self_scope(self, scope: Scope | None):
        prev = self.current_self_scope
        self.current_self_scope = scope
        try:
            yield self.current_self_scope
        finally:
            self.current_self_scope = prev

    def find_self_scope(self, t: AST, scope: Scope) -> Scope | None:
        match t:
            case Object() if t.self_scope is not None:
                return t.self_scope
            case Document():
                return self.find_self_scope(t.body, Scope())
            case Id():
                return head_or_none(
                    self.find_self_scope(target, binding.scope)
                    for binding in maybe(scope.get(t))
                    for target in maybe(binding.target)
                )
            case Field():
                return head_or_none(
                    self.find_self_scope(t.value, var_scope)
                    for obj in maybe(t.enclosing_obj)
                    for var_scope in maybe(obj.var_scope)
                )
            case FieldAccess():
                return head_or_none(
                    self.find_self_scope(target, binding.scope)
                    for parent_scope in maybe(self.find_self_scope(t.obj, scope))
                    for binding in maybe(parent_scope.get(t.field))
                    for target in maybe(binding.target)
                )
            case Binary(_, _, _, rhs):
                return self.find_self_scope(rhs, self.current_var_scope)
            case Import(_, "import", path):
                return head_or_none(
                    self.find_self_scope(index.doc, index.current_var_scope)
                    for index in maybe(self.importee_index(path.raw))
                )
            case Local():
                return head_or_none(
                    self.find_self_scope(t.body, local_scope)
                    for local_scope in maybe(t.scope)
                )
            case Binary(_, Operator.Plus, _, rhs):
                return self.find_self_scope(rhs, scope)
            case Self():
                return t.scope
            case Super():
                return t.scope
            case _:
                return None

    def visit_local(self, e: Local):
        for b in e.binds:
            self.visit_bind(b)

        with self.var_scope(self.current_var_scope.nest()) as nested:
            e.scope = nested
            self.visit(e.body)

    def visit_bind(self, b: Bind):
        self.current_var_scope.bind(b.id.name, b.id.location, b.value)

        match b.value:
            case Fn():
                kind = L.SymbolKind.Function
            case _:
                kind = L.SymbolKind.Variable

        doc_symbol = L.DocumentSymbol(
            name=b.id.name,
            kind=kind,
            range=b.id.location.range,
            selection_range=b.location.range,
        )

        self.add_document_symbol(doc_symbol)
        with self.parent_symbol(doc_symbol):
            with self.var_scope(self.current_var_scope.nest()):
                self.visit(b.value)

    def visit_fn(self, e: Fn):
        # NOTE: In a Jsonnet function, any parameter's default value expression can
        # reference any other peer parameters, e.g.:
        #
        #   local f(x = y, y, x = z) =
        #       x + y + z;
        #   f(y = 2)
        #
        # This requires all parameters to be bound before traversing any parameter
        # default value expressions. This is also why parameters must be handled in
        # `visit_fn` instead of `visit_param`.
        with self.var_scope(self.current_var_scope.nest()):
            for p in e.params:
                self.current_var_scope.bind(p.id.name, p.id.location, p.default)

            for p in e.params:
                doc_symbol = L.DocumentSymbol(
                    name=p.id.name,
                    kind=L.SymbolKind.Variable,
                    range=p.id.location.range,
                    selection_range=p.location.range,
                )

                self.add_document_symbol(doc_symbol)

                if p.default is not None:
                    with self.parent_symbol(doc_symbol):
                        self.visit(p.default)

            self.visit(e.body)

    def visit_for_spec(self, s: ForSpec):
        self.add_document_symbol(
            L.DocumentSymbol(
                name=s.id.name,
                kind=L.SymbolKind.Variable,
                range=s.id.location.range,
                selection_range=s.location.range,
            )
        )

        self.current_var_scope.bind(s.id.name, s.id.location, s.container)

        self.visit(s.container)

    def visit_id(self, e: Id):
        if e.is_variable and (binding := self.current_var_scope.get(e)) is not None:
            self.add_reference(e, binding)

    def visit_field_key(self, e: Object, f: Field):
        assert e.self_scope is not None

        f.enclosing_obj = e

        match f.key:
            case FixedKey(_, Id(_, name)):
                e.self_scope.bind(name, f.key.location, f)
                self.add_document_symbol(
                    L.DocumentSymbol(
                        name=name,
                        kind=L.SymbolKind.Field,
                        range=f.key.location.range,
                        selection_range=f.location.range,
                    )
                )
            case FixedKey(_, Str(_, raw)):
                e.self_scope.bind(raw, f.key.location, f)
                self.add_document_symbol(
                    L.DocumentSymbol(
                        name=raw,
                        kind=L.SymbolKind.Field,
                        range=f.key.location.range,
                        selection_range=f.location.range,
                    )
                )

        # Adds an optional inlay hint for visibility and inheritance.
        label_parts = []

        match f.visibility:
            case Visibility.Hidden:
                label_parts.append("hidden")
            case Visibility.Forced:
                label_parts.append("forced visible")

        if f.inherited:
            label_parts.append("inherited")

        if len(label_parts) > 0:
            self.add_hint(
                L.InlayHint(
                    position=f.key.location.range.end,
                    label=", ".join(label_parts),
                    padding_left=True,
                    padding_right=True,
                )
            )

    def visit_field_value(self, e: Object, f: Field):
        del e
        self.visit(f.value)

    def resolve_importee_path(self, raw_path: str) -> Path:
        root = Path.from_uri(self.workspace_index.root_uri)

        if raw_path.startswith("../") or raw_path.startswith("./"):
            return Path.from_uri(self.uri).parent.joinpath(raw_path).absolute()
        elif (path := root.joinpath(raw_path).absolute()).exists():
            return path
        else:
            return root.joinpath("vendor", raw_path)

    def importee_index(self, raw_path: str) -> "DocumentIndex | None":
        path = self.resolve_importee_path(raw_path)
        index = self.workspace_index.docs.get(path.as_uri())

        return index or (
            self.workspace_index.get_or_load(
                uri=path.as_uri(),
                source=path.read_text(encoding="utf-8"),
            )
            if path.exists()
            else None
        )

    def visit_import(self, e: Import):
        importee_path = self.resolve_importee_path(e.path.raw)
        importee_uri = importee_path.as_uri()

        if importee_path.exists() and importee_path.is_file():
            self.links.append(
                L.DocumentLink(
                    range=e.path.location.range,
                    target=importee_uri,
                )
            )

        self.hovers[LocationKey(e.path.location)] = L.Hover(importee_uri)

        self.add_document_symbol(
            L.DocumentSymbol(
                name=e.path.raw,
                kind=L.SymbolKind.File,
                range=e.path.location.range,
                selection_range=e.location.range,
            )
        )

        self.add_hint(
            L.InlayHint(
                position=e.path.location.range.end,
                label=Icon.File,
            )
        )

    def visit_object(self, e: Object):
        e.var_scope = self.current_var_scope
        e.super_scope = self.current_super_scope
        e.self_scope = Scope.empty() if e.super_scope is None else e.super_scope.nest()

        with self.self_scope(e.self_scope):
            super().visit_object(e)

    def visit_field_access(self, e: FieldAccess):
        self.visit(e.obj)

        for scope in maybe(self.find_self_scope(e.obj, self.current_var_scope)):
            for binding in maybe(scope.get(e.field)):
                self.add_reference(e.field, binding)

    def visit_self(self, e: Self):
        e.scope = self.current_self_scope

    def visit_super(self, e: Super):
        e.scope = self.current_super_scope

    def visit_binary(self, e: Binary):
        self.visit(e.lhs)
        base_self = self.find_self_scope(e.lhs, self.current_var_scope)
        with self.super_scope(base_self):
            self.visit(e.rhs)


LocationMap = dict[LocationKey, list[L.Location]]


class WorkspaceIndex:
    def __init__(self, root_uri: URI):
        self.root_uri = root_uri
        self.docs: dict[URI, DocumentIndex] = {}

    def definitions(self, uri: URI, position: L.Position) -> list[L.Location]:
        local_defs = [
            location
            for doc in maybe(self.docs.get(uri))
            for location in doc.definition(position)
        ]

        return local_defs

    def references(self, uri: URI, position: L.Position) -> list[L.Location]:
        return [
            location
            for doc in maybe(self.docs.get(uri))
            for location in doc.references(position)
        ]

    def load(self, uri: URI, source: str | None):
        self.docs[uri] = DocumentIndex.load(self, uri, source)

    def get_or_load(self, uri: URI, source: str | None = None) -> DocumentIndex:
        if uri not in self.docs:
            self.load(uri, source)
        return self.docs[uri]
