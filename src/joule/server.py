import logging
from pathlib import Path

import lsprotocol.types as L
from pygls.lsp.server import LanguageServer

from joule.ast import URI
from joule.maybe import maybe
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
    def set_workspace_root(self, root_uri: URI):
        folder = L.WorkspaceFolder(root_uri, Path.from_uri(root_uri).name)
        self.workspace.add_folder(folder)
        self.document_loader = DocumentLoader(root_uri)


server = JouleLanguageServer("joule", "v0.1")


@server.feature(L.INITIALIZE)
def initialize(ls: JouleLanguageServer, params: L.InitializeParams):
    for root_uri in maybe(params.root_uri):
        log.info("Discovered workspace root: %s", root_uri)
        root = Path.from_uri(root_uri).absolute()
        ls.set_workspace_root(root.as_uri())

    return L.InitializeResult(
        capabilities=L.ServerCapabilities(
            text_document_sync=L.TextDocumentSyncKind.Full,
        ),
        server_info=L.ServerInfo(
            name=ls.name,
            version=ls.version,
        ),
    )


@server.feature(L.TEXT_DOCUMENT_DID_OPEN)
def did_open(ls: JouleLanguageServer, params: L.DidOpenTextDocumentParams):
    doc = params.text_document

    # If the workspace root is not yet discovered, set the root as the parent folder of
    # the first document opened.
    if len(ls.workspace.folders) == 0:
        parent_uri = Path.from_uri(doc.uri).absolute().parent.as_uri()
        ls.set_workspace_root(parent_uri)

    ls.document_loader.load(doc.uri, doc.text)


@server.feature(L.TEXT_DOCUMENT_DID_CHANGE)
def did_change(ls: JouleLanguageServer, params: L.DidChangeTextDocumentParams):
    doc = ls.workspace.get_text_document(params.text_document.uri)
    ls.document_loader.load(doc.uri, doc.source)


@server.feature(L.TEXT_DOCUMENT_DOCUMENT_SYMBOL)
def document_symbol(ls: JouleLanguageServer, params: L.DocumentSymbolParams):
    doc = ls.workspace.get_text_document(params.text_document.uri)
    return (
        DocumentSymbolProvider().serve(tree)
        if (tree := ls.document_loader.get_or_load(doc.uri, doc.source))
        else None
    )


@server.feature(L.TEXT_DOCUMENT_DEFINITION)
def definition(ls: JouleLanguageServer, params: L.DefinitionParams):
    doc = ls.workspace.get_text_document(params.text_document.uri)
    return (
        DefinitionProvider(ls.document_loader).serve(tree, params.position)
        if (tree := ls.document_loader.get_or_load(doc.uri, doc.source))
        else None
    )


@server.feature(L.TEXT_DOCUMENT_REFERENCES)
def references(ls: JouleLanguageServer, params: L.ReferenceParams):
    doc = ls.workspace.get_text_document(params.text_document.uri)
    return (
        ReferencesProvider().serve(tree, params.position)
        if (tree := ls.document_loader.get_or_load(doc.uri, doc.source))
        else None
    )


@server.feature(L.TEXT_DOCUMENT_INLAY_HINT)
def inlay_hint(ls: JouleLanguageServer, params: L.InlayHintParams):
    doc = ls.workspace.get_text_document(params.text_document.uri)
    return (
        InlayHintProvider().serve(tree)
        if (tree := ls.document_loader.get_or_load(doc.uri, doc.source))
        else None
    )


@server.feature(L.TEXT_DOCUMENT_DOCUMENT_HIGHLIGHT)
def document_highlight(ls: JouleLanguageServer, params: L.DocumentHighlightParams):
    doc = ls.workspace.get_text_document(params.text_document.uri)
    return (
        DocumentHighlightProvider().serve(tree, params.position)
        if (tree := ls.document_loader.get_or_load(doc.uri, doc.source))
        else None
    )


@server.feature(L.TEXT_DOCUMENT_RENAME)
def rename(ls: JouleLanguageServer, params: L.RenameParams):
    doc = ls.workspace.get_text_document(params.text_document.uri)
    return (
        RenameProvider().serve(tree, params.position, params.new_name)
        if (tree := ls.document_loader.get_or_load(doc.uri, doc.source))
        else None
    )


@server.feature(L.TEXT_DOCUMENT_PREPARE_RENAME)
def prepare_rename(ls: JouleLanguageServer, params: L.PrepareRenameParams):
    doc = ls.workspace.get_text_document(params.text_document.uri)
    return (
        RenameProvider().prepare(tree, params.position)
        if (tree := ls.document_loader.get_or_load(doc.uri, doc.source))
        else None
    )


@server.feature(L.TEXT_DOCUMENT_FOLDING_RANGE)
def folding_range(ls: JouleLanguageServer, params: L.PrepareRenameParams):
    doc = ls.workspace.get_text_document(params.text_document.uri)
    return (
        FoldingRangeProvider().serve(tree)
        if (tree := ls.document_loader.get_or_load(doc.uri, doc.source))
        else None
    )
