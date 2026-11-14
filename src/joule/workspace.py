from pathlib import Path

from joule.analysis.imports import ImportGraph
from joule.analysis.scopes import analyze
from joule.syntax import trees as T


def analyze_document(uri: str, source: str | None = None) -> T.Document | None:
    try:
        raw = Path.from_uri(uri).read_bytes() if source is None else source.encode()
        doc = T.Document.from_cst(T.parse(raw).root_node)
    except OSError, T.MalformedError:
        return None

    analyze(doc)
    return doc


class FolderIndex:
    import_graph: ImportGraph

    def __init__(self, import_graph: ImportGraph):
        self.import_graph = import_graph

    def on_file_created(self, path: Path):
        self.import_graph.on_file_created(path)

    def on_file_changed(self, path: Path):
        self.import_graph.on_file_changed(path)

    def on_file_deleted(self, path: Path):
        self.import_graph.on_file_deleted(path)
