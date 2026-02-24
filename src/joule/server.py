import logging
from pathlib import Path

import lsprotocol.types as L
from pygls.lsp.server import LanguageServer

from joule.ast import URI
from joule.model import DocumentLoader
from joule.providers import (
    DefinitionProvider,
    DocumentHighlightProvider,
    DocumentSymbolProvider,
    FoldingRangeProvider,
    InlayHintProvider,
    ReferencesProvider,
    RenameProvider,
)

log = logging.root


class JouleLanguageServer(LanguageServer):
    @property
    def loader(self) -> DocumentLoader:
        try:
            return self._loader
        except AttributeError:
            workspace_uri: URI | None = None

            match list(self.workspace.folders.keys()):
                case [_, _, *_]:
                    raise RuntimeError("Joule does not support multi-workspace.")
                case [workspace_uri]:
                    pass
                case _ if (workspace_uri := self.workspace.root_uri) is not None:
                    Path.from_uri(workspace_uri).resolve()
                case _ if (workspace_path := self.workspace.root_path) is not None:
                    workspace_uri = Path(workspace_path).resolve().as_uri()

            self._loader = DocumentLoader(workspace_uri)
            return self._loader


server = JouleLanguageServer("joule", "v0.1")


@server.feature(L.TEXT_DOCUMENT_DID_OPEN)
def did_open(ls: JouleLanguageServer, params: L.DidOpenTextDocumentParams):
    doc = params.text_document
    ls.loader.load(doc.uri, doc.text)


@server.feature(L.TEXT_DOCUMENT_DID_CHANGE)
def did_change(ls: JouleLanguageServer, params: L.DidChangeTextDocumentParams):
    doc = ls.workspace.get_text_document(params.text_document.uri)
    ls.loader.load(doc.uri, doc.source)


@server.feature(L.TEXT_DOCUMENT_DOCUMENT_SYMBOL)
def document_symbol(ls: JouleLanguageServer, params: L.DocumentSymbolParams):
    doc = ls.workspace.get_text_document(params.text_document.uri)
    return (
        DocumentSymbolProvider().serve(tree)
        if (tree := ls.loader.get(doc.uri, doc.source))
        else None
    )


@server.feature(L.TEXT_DOCUMENT_DEFINITION)
def definition(ls: JouleLanguageServer, params: L.DefinitionParams):
    doc = ls.workspace.get_text_document(params.text_document.uri)
    return (
        DefinitionProvider(ls.loader).serve(tree, params.position)
        if (tree := ls.loader.get(doc.uri, doc.source))
        else None
    )


@server.feature(L.TEXT_DOCUMENT_REFERENCES)
def references(ls: JouleLanguageServer, params: L.ReferenceParams):
    doc = ls.workspace.get_text_document(params.text_document.uri)
    return (
        ReferencesProvider(ls.loader).serve(tree, params.position)
        if (tree := ls.loader.get(doc.uri, doc.source))
        else None
    )


@server.feature(L.TEXT_DOCUMENT_INLAY_HINT)
def inlay_hint(ls: JouleLanguageServer, params: L.InlayHintParams):
    doc = ls.workspace.get_text_document(params.text_document.uri)
    return (
        InlayHintProvider().serve(tree)
        if (tree := ls.loader.get(doc.uri, doc.source))
        else None
    )


@server.feature(L.TEXT_DOCUMENT_DOCUMENT_HIGHLIGHT)
def document_highlight(ls: JouleLanguageServer, params: L.DocumentHighlightParams):
    doc = ls.workspace.get_text_document(params.text_document.uri)
    return (
        DocumentHighlightProvider().serve(tree, params.position)
        if (tree := ls.loader.get(doc.uri, doc.source))
        else None
    )


@server.feature(L.TEXT_DOCUMENT_RENAME)
def rename(ls: JouleLanguageServer, params: L.RenameParams):
    doc = ls.workspace.get_text_document(params.text_document.uri)
    return (
        RenameProvider().serve(tree, params.position, params.new_name)
        if (tree := ls.loader.get(doc.uri, doc.source))
        else None
    )


@server.feature(L.TEXT_DOCUMENT_PREPARE_RENAME)
def prepare_rename(ls: JouleLanguageServer, params: L.PrepareRenameParams):
    doc = ls.workspace.get_text_document(params.text_document.uri)
    return (
        RenameProvider().prepare(tree, params.position)
        if (tree := ls.loader.get(doc.uri, doc.source))
        else None
    )


@server.feature(L.TEXT_DOCUMENT_FOLDING_RANGE)
def folding_range(ls: JouleLanguageServer, params: L.PrepareRenameParams):
    doc = ls.workspace.get_text_document(params.text_document.uri)
    return (
        FoldingRangeProvider().serve(tree)
        if (tree := ls.loader.get(doc.uri, doc.source))
        else None
    )
