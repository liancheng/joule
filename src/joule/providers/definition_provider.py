import lsprotocol.types as L

from joule.ast import AST, Id, Document
from joule.util import maybe
from joule.visitor import Visitor


class DefinitionProvider(Visitor):
    @staticmethod
    def serve(tree: Document, pos: L.Position) -> list[L.Location]:
        return [
            location
            for node in maybe(tree.node_at(pos))
            for location in DefinitionProvider.find_definition(node)
        ]

    @staticmethod
    def find_definition(node: AST) -> list[L.Location]:
        match node:
            case Id.VarRef(_, name):
                return DefinitionProvider.find_var_definition(name, node.parent)
            case Id.FieldRef(_, name):
                return DefinitionProvider.find_field_definition(name, node.parent)
            case _:
                return []

    @staticmethod
    def find_var_definition(name: str, ancestor: AST | None) -> list[L.Location]:
        if ancestor is None:
            return []

        return next(
            (
                [binding.location]
                for scope in maybe(ancestor.var_scope)
                for binding in maybe(scope.get(name))
            ),
            # Falls back to the ancestor's parent when:
            #  * The ancestor does not have a variable scope, or
            #  * `name` is not bound in the ancestor's variable scope.
            DefinitionProvider.find_var_definition(name, ancestor.parent),
        )

    @staticmethod
    def find_field_definition(name: str, ancestor: AST | None) -> list[L.Location]:
        del name, ancestor
        # Not implemented
        return []
