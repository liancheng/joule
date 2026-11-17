from collections.abc import Iterable

import lsprotocol.types as L

from joule.maybe import maybe
from joule.syntax import trees as T


class DefinitionProvider:
    uri: str
    doc: T.Document

    def __init__(self, uri: str, doc: T.Document):
        self.uri = uri
        self.doc = doc

    def serve(self, pos: L.Position) -> list[L.Location]:
        return [
            location
            for node in maybe(self.doc.node_at(T.Point.from_lsp(pos)))
            for location in self.find_definition(node)
        ]

    def find_definition(self, node: T.Tree) -> Iterable[L.Location]:
        match node:
            case T.Id.FieldRef():
                return self.find_field_definition(node)
            case T.Id.VarRef():
                return self.find_var_definition(node)
            case _:
                return ()

    def find_var_definition(self, node: T.Id.VarRef) -> Iterable[L.Location]:
        return (var.span.to_location(self.uri) for var in maybe(node.var))

    def find_field_definition(self, node: T.Id.FieldRef) -> Iterable[L.Location]:
        return (
            binding.id.span.to_location(self.uri)
            for scope in self.find_field_scope(node)
            for binding in maybe(scope.get(node.name))
        )

    def find_field_scope(self, node: T.Tree) -> Iterable[T.FieldScope]:
        match node:
            case T.Id.FieldRef():
                return (
                    scope
                    for parent in maybe(node.parent)
                    for scope in self.find_field_scope(parent)
                )

            case T.Id.VarRef():
                return (
                    scope
                    for var in maybe(node.var)
                    for binding in maybe(var.binding)
                    for scope in self.find_field_scope(binding.target)
                )

            case T.If():
                return (
                    scope
                    for expr in (node.consequence, node.alternative)
                    for scope in self.find_field_scope(expr)
                )

            case T.FieldAccess():
                return self.find_field_scope(node.target)

            case T.Object():
                return maybe(node.field_scope)

            case _:
                return ()
