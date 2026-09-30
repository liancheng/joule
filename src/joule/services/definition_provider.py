from collections.abc import Iterable

from joule import trees as T
from joule.maybe import maybe


class DefinitionProvider:
    def __init__(self, doc: T.Document):
        self.doc = doc

    def serve(self, point: T.Point) -> list[T.Span]:
        return [
            span
            for node in maybe(self.doc.node_at(point))
            for span in self.find_definition(node)
        ]

    def find_definition(self, node: T.Tree) -> Iterable[T.Span]:
        match node:
            case T.Id.VarRef():
                return (var.span for var in maybe(node.var))
            case _:
                return ()
