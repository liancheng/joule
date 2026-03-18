import logging
import re
from pathlib import Path
from typing import Iterable

import lsprotocol.types as L

from joule import ast as A
from joule.ast import AnalysisPhase
from joule.maybe import maybe
from joule.model import DocumentLoader
from joule.providers.definition_provider import DefinitionProvider

log = logging.getLogger(__name__)


class ReferencesProvider:
    def __init__(self, loader: DocumentLoader) -> None:
        self.loader = loader

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
        def prune(path: Path) -> A.Document | None:
            pattern = re.compile(rf"\b{re.escape(field.name)}\b")
            uri = path.absolute().as_uri()
            match self.loader.trees.get(uri):
                case A.Document() as tree:
                    return tree
                case _ if re.search(pattern, source := path.read_text()):
                    return self.loader.load_and_cache_from_source(uri, source)
                case _:
                    return None

        return (
            ref
            for workspace_path in maybe(self.loader.workspace_path)
            for path in self.loader.source_files(workspace_path)
            for tree in maybe(prune(path))
            for ref in tree.field_refs
            if ref.name == field.name
            for binding in DefinitionProvider(self.loader).find_field_binding(ref)
            if isinstance(fixed_key := binding.target.key, A.FixedKey)
            if fixed_key.id == field
        )
