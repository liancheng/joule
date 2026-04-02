from itertools import chain
from typing import Iterable

import lsprotocol.types as L

from joule import ast as A
from joule.ast import AnalysisPhase
from joule.maybe import maybe
from joule.model import DocumentStore
from joule.providers import DefinitionProvider


class ReferencesProvider:
    def __init__(self, store: DocumentStore) -> None:
        self.store = store

    def serve(self, tree: A.Document, pos: L.Position) -> list[L.Location] | None:
        assert tree.analysis_phase == AnalysisPhase.ScopeResolved
        refs = [
            ref.location
            for node in maybe(tree.node_at(pos))
            for ref in self.find_references(node)
        ]
        return refs if len(refs) > 0 else None

    def find_references(self, node: A.AST) -> Iterable[A.Expr]:
        match node:
            case A.Id.Field():
                return self.find_field_references(node)
            case A.Id.Var():
                return node.references
            case _:
                return ()

    def find_field_references(self, field: A.Id.Field) -> Iterable[A.Id.FieldRef]:
        return (
            ref
            for uri in chain(
                self.store.recursive_importers(field.location.uri),
                [field.location.uri],
            )
            for tree in maybe(self.store.get(uri))
            for ref in tree.field_refs
            if ref.name == field.name
            for binding in DefinitionProvider(self.store).find_field_binding(ref)
            if isinstance(fixed_key := binding.target.key, A.FixedKey)
            if fixed_key.id == field
        )
