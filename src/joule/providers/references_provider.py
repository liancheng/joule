import re
from typing import Iterable

import lsprotocol.types as L

from joule.ast import AST, AnalysisPhase, Document, FieldAccess, FixedKey, Id
from joule.maybe import maybe
from joule.model import DocumentLoader
from joule.providers.definition_provider import enclosing_node
from joule.visitor import Visitor


class FieldRefFinder(Visitor):
    def __init__(self, loader: DocumentLoader, key: FixedKey) -> None:
        from joule.providers import DefinitionProvider

        self.loader = loader
        self.key = key
        self.definition_provider = DefinitionProvider(self.loader)
        self.refs: list[Id.FieldRef] = []

    def search(self, tree: Document) -> list[Id.FieldRef]:
        self.visit(tree)
        self.refs.sort(key=lambda ref: ref.location.uri)
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

    def serve(self, tree: Document, pos: L.Position) -> list[L.Location] | None:
        assert tree.analysis_phase == AnalysisPhase.ScopeResolved
        refs = [
            ref.location
            for node in maybe(tree.node_at(pos))
            for ref in self.find_references(node)
        ]
        return refs if len(refs) > 0 else None

    def find_references(self, node: AST) -> Iterable[AST]:
        match node:
            case Id.Field():
                pattern = re.compile(f"\\b{node.name}\\b")
                return (
                    ref
                    for key in maybe(enclosing_node(node, FixedKey, level=1))
                    for uri, source in self.loader.load_all_sources()
                    for _ in maybe(re.search(pattern, source))
                    for tree in maybe(self.loader.load(uri, source))
                    for ref in FieldRefFinder(self.loader, key).search(tree)
                )
            case Id.Var():
                return node.references
            case _:
                return ()
