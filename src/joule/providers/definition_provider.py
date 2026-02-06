import lsprotocol.types as L

from joule.ast import (
    AST,
    Binding,
    Document,
    Dollar,
    Field,
    FieldAccess,
    Id,
    Object,
    Scope,
)
from joule.util import maybe


class DefinitionProvider:
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
        return [
            binding
            for parent in maybe(field_ref.parent)
            for scope in self.find_field_scope(parent.to(FieldAccess).obj)
            for binding in maybe(scope.get(field_ref.name))
        ]

    def find_outer_most_object(self, node: AST | None) -> Object | None:
        def walk(node: AST | None, sofar: Object | None) -> Object | None:
            match node:
                case None:
                    return sofar
                case Object():
                    return walk(node.parent, node)
                case _:
                    return walk(node.parent, sofar)

        return walk(node, None)

    def find_field_scope(self, node: AST) -> list[Scope]:
        match node:
            case Dollar():
                return [
                    scope
                    for obj in maybe(self.find_outer_most_object(node))
                    for scope in maybe(obj.field_scope)
                ]
            case FieldAccess() as f:
                return [
                    scope
                    for binding in self.find_field_binding(f.field)
                    for scope in self.find_field_scope(binding.target.to(Field).value)
                ]
            case Id.VarRef() as var_ref:
                return [
                    scope
                    for binding in self.find_var_binding(var_ref)
                    for scope in self.find_field_scope(binding.target)
                ]
            case Object():
                return [scope for scope in maybe(node.field_scope)]
            case _:
                return []
