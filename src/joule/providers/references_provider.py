import re
from pathlib import Path
from typing import Iterable

import lsprotocol.types as L

from joule.ast import AST, AnalysisPhase, Document, Expr, FixedKey, Id
from joule.maybe import maybe
from joule.model import DocumentLoader
from joule.providers.definition_provider import DefinitionProvider


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

    def find_references(self, node: AST) -> Iterable[Expr]:
        self.def_provider = DefinitionProvider(self.loader)
        match node:
            case Id.Field():
                return self.find_field_references(node)
            case Id.Var():
                return node.references
            case _:
                return ()

    def find_field_references(self, field: Id.Field) -> Iterable[Id.FieldRef]:
        def prune(path: Path) -> Document | None:
            pattern = re.compile(f"\\b{field.name}\\b")
            uri = path.absolute().as_uri()
            match self.loader.trees.get(uri):
                case Document() as tree:
                    return tree
                case _ if re.search(pattern, source := path.read_text()):
                    return self.loader.load(uri, source)
                case _:
                    return None

        return (
            ref
            for workspace_path in maybe(self.loader.workspace_path)
            for path in self.loader.walk(workspace_path)
            for tree in maybe(prune(path))
            for ref in tree.field_refs
            if ref.name == field.name
            for binding in self.def_provider.find_field_binding(ref)
            if isinstance(fixed_key := binding.target.key, FixedKey)
            if fixed_key.id == field
        )
