import lsprotocol.types as L

from joule.ast import AST, Binding, Document, FieldAccess, Id, Object, Scope
from joule.util import maybe
from joule.visitor import Visitor


class DefinitionProvider(Visitor):
    def __init__(self, tree: Document) -> None:
        self.tree = tree

    def serve(self, pos: L.Position) -> list[L.Location]:
        return [
            location
            for node in maybe(self.tree.node_at(pos))
            for location in self.find_definition(node)
        ]

    def find_definition(self, node: AST) -> list[L.Location]:
        match node:
            case Id.VarRef():
                return [binding.location for binding in self.find_var_binding(node)]
            case Id.FieldRef():
                return [binding.location for binding in self.find_field_binding(node)]
            case _:
                return []

    def find_var_binding(self, id: Id.VarRef) -> list[Binding]:
        return [
            binding
            for scope in maybe(id.bound_in)
            for binding in maybe(scope.get(id.name))
        ]

    def find_field_binding(self, field_ref: Id.FieldRef) -> list[Binding]:
        match field_ref.parent:
            case FieldAccess() as parent:
                return [
                    binding
                    for scope in self.find_field_scope(parent.obj)
                    for binding in maybe(scope.get(field_ref.name))
                ]
            case _:
                return []

    def find_field_scope(self, node: AST) -> list[Scope]:
        match node:
            case Object():
                return [scope for scope in maybe(node.field_scope)]
            case Id.VarRef() as var_ref:
                return [
                    scope
                    for binding in self.find_var_binding(var_ref)
                    for scope in self.find_field_scope(binding.to)
                ]
            case _:
                return []
