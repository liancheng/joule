from joule.ast import Document, FieldAccess, Id
from joule.model import DocumentLoader
from joule.providers import DefinitionProvider
from joule.visitor import Visitor


class FieldRefResolver(Visitor):
    def __init__(self, loader: DocumentLoader) -> None:
        self.loader = loader
        self.definition_provider = DefinitionProvider(self.loader)
        self.refs: list[Id.FieldRef] = []

    def resolve(self, tree: Document) -> list[Id.FieldRef]:
        self.visit(tree)
        return self.refs

    def visit_field_access(self, e: FieldAccess):
        super().visit_field_access(e)
        for binding in self.definition_provider.find_field_binding(e.field):
            e.field.binding = binding
            self.refs.append(e.field)
