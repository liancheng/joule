import lsprotocol.types as L

from joule.ast import (
    AST,
    Binding,
    Document,
    Dollar,
    Field,
    FieldAccess,
    Id,
    If,
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
                return [b.id.location for b in self.find_var_binding(node)]
            case Id.FieldRef():
                return [b.id.location for b in self.find_field_binding(node)]
            case _:
                return []

    def find_var_binding(self, id: Id.VarRef) -> list[Binding]:
        return [
            binding
            for var in maybe(id.var)
            for scope in maybe(var.bound_in)
            for binding in maybe(scope.get(id.name))
        ]

    def find_field_binding(self, field_ref: Id.FieldRef) -> list[Binding]:
        return [
            binding
            for parent in maybe(field_ref.parent)
            for scope in self.find_field_scope(parent.to(FieldAccess).obj)
            for binding in maybe(scope.get(field_ref.name))
        ]

    def find_field_scope(self, node: AST) -> list[Scope]:
        match node:
            case Dollar():

                def outer_most_object(
                    node: AST | None, so_far: Object | None = None
                ) -> Object | None:
                    match node:
                        case None:
                            return so_far
                        case Object():
                            return outer_most_object(node.parent, node)
                        case _:
                            return outer_most_object(node.parent, so_far)

                return [
                    scope
                    for obj in maybe(outer_most_object(node))
                    for scope in maybe(obj.field_scope)
                ]

            case FieldAccess():
                return [
                    scope
                    for binding in self.find_field_binding(node.field)
                    for scope in self.find_field_scope(binding.target.to(Field).value)
                ]

            case Id.VarRef():
                return [
                    scope
                    for binding in self.find_var_binding(node)
                    for scope in self.find_field_scope(binding.target)
                ]

            case If():
                return [
                    scope for e in node.branches for scope in self.find_field_scope(e)
                ]

            case Object():
                return [scope for scope in maybe(node.field_scope)]

            case _:
                return []
