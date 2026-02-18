from typing import Iterable

import lsprotocol.types as L

from joule.ast import AST, AnalysisPhase, Document, FieldAccess, FixedKey, Id
from joule.maybe import maybe
from joule.model import DocumentLoader
from joule.providers import DefinitionProvider
from joule.visitor import Visitor


class FieldRefFinder(Visitor):
    def __init__(self, loader: DocumentLoader, key: FixedKey) -> None:
        self.loader = loader
        self.key = key
        self.definition_provider = DefinitionProvider(self.loader)
        self.refs: list[Id.FieldRef] = []

    def find_references(self, tree: Document) -> list[Id.FieldRef]:
        self.visit(tree)
        return self.refs

    def visit_field_access(self, e: FieldAccess):
        super().visit_field_access(e)
        if e.field.name == self.key.id.name:
            for binding in self.definition_provider.find_field_binding(e.field):
                if binding.target.key == self.key:
                    self.refs.append(e.field)


class ReferencesProvider:
    def __init__(self, loader: DocumentLoader) -> None:
        self.loader = loader

    def serve(self, tree: Document, pos: L.Position) -> list[L.Location]:
        assert tree.analysis_phase == AnalysisPhase.ScopeResolved
        return [
            location
            for node in maybe(tree.node_at(pos))
            for location in self.find_references(node)
        ]

    def find_references(self, node: AST) -> Iterable[L.Location]:
        match node:
            case Id.Field():
                return (
                    ref.location
                    for key in maybe(node.parent)
                    if isinstance(key, FixedKey)
                    if (finder := FieldRefFinder(self.loader, key))
                    for tree in maybe(self.loader.get(node.location.uri))
                    for ref in finder.find_references(tree)
                )
            case Id.Var():
                return (ref.location for ref in node.references)
            case _:
                return ()
