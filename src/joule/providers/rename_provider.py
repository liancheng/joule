import lsprotocol.types as L

from joule import ast as A
from joule.ast import AnalysisPhase
from joule.maybe import head_or_none, maybe


class RenameProvider:
    def prepare(
        self, tree: A.Document, pos: L.Position
    ) -> L.PrepareRenamePlaceholder | None:
        assert tree.analysis_phase == AnalysisPhase.ScopeResolved
        return head_or_none(
            L.PrepareRenamePlaceholder(range=node.location.range, placeholder=node.name)
            for node in maybe(tree.node_at(pos))
            if isinstance(node, A.Id.Var) or isinstance(node, A.Id.VarRef)
        )

    def serve(
        self,
        tree: A.Document,
        pos: L.Position,
        new_name: str,
    ) -> L.WorkspaceEdit:
        match tree.node_at(pos):
            case A.Id.Var() as var:
                text_edits = [
                    L.TextEdit(range=node.location.range, new_text=new_name)
                    for node in var.references + [var]
                ]
            case A.Id.VarRef() as ref:
                text_edits = [
                    L.TextEdit(range=node.location.range, new_text=new_name)
                    for var in maybe(ref.var)
                    for node in var.references + [var]
                ]
            case _:
                text_edits = []

        return L.WorkspaceEdit(changes={tree.location.uri: text_edits})
