from pathlib import Path

from joule.analysis.imports import ImportGraph
from joule.analysis.scopes import resolve
from joule.syntax import trees as T


def resolve_document(uri: str) -> T.Document | None:
    try:
        source = Path.from_uri(uri).read_bytes()
        doc = T.Document.from_cst(T.parse(source).root_node)
    except OSError, T.MalformedError:
        return None

    resolve(doc)
    return doc


class FolderIndex:
    import_graph: ImportGraph

    def __init__(self, import_graph: ImportGraph):
        self.import_graph = import_graph

    def on_file_created(self, path: Path):
        self.import_graph.file_created(path)

    def on_file_changed(self, path: Path):
        self.import_graph.file_changed(path)

    def on_file_deleted(self, path: Path):
        self.import_graph.file_deleted(path)

    # TODO: Caches resolved AST trees and invalidates on updates.
    def resolve_document(self, uri: str) -> T.Document | None:
        return resolve_document(uri)
