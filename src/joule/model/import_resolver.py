from joule.ast import URI, Import, ImportType
from joule.visitor import Visitor

from .document_loader import DocumentLoader


class ImportResolver(Visitor):
    def __init__(self, loader: DocumentLoader) -> None:
        self.loader = loader
        self.importees: list[URI] = []

    def visit_import(self, e: Import):
        super().visit_import(e)
        if e.type == ImportType.Default:
            if path := self.loader.resolve_importee(e.importee):
                self.importees.append(path.absolute().as_uri())
