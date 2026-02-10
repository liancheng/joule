import lsprotocol.types as L

from joule.ast import AnalysisPhase, Document, Id
from joule.util import maybe


class RenameProvider:
    def __init__(self, tree: Document) -> None:
        assert tree.analysis_phase == AnalysisPhase.ScopeResolved
        self.tree = tree

    def prepare(self, pos: L.Position) -> L.PrepareRenamePlaceholder | None:
        match node := self.tree.node_at(pos):
            case Id.Var() | Id.VarRef():
                return L.PrepareRenamePlaceholder(
                    range=node.location.range,
                    placeholder=node.name,
                )
            case _:
                return None

    def serve(self, pos: L.Position, new_name: str) -> list[L.WorkspaceEdit]:
        match self.tree.node_at(pos):
            case Id.Var() as var:
                text_edits = [
                    L.TextEdit(range=node.location.range, new_text=new_name)
                    for node in var.references + [var]
                ]
            case Id.VarRef() as ref:
                text_edits = [
                    L.TextEdit(range=node.location.range, new_text=new_name)
                    for var in maybe(ref.var)
                    for node in var.references + [var]
                ]
            case _:
                text_edits = []

        return [L.WorkspaceEdit(changes={self.tree.location.uri: text_edits})]
