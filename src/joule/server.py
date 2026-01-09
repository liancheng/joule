import logging
from itertools import chain
from pathlib import Path
from typing import Iterator

import lsprotocol.types as L
from pygls.lsp.server import LanguageServer

from joule.ast import location_contains
from joule.model import WorkspaceIndex
from joule.typing import URI
from joule.util import head_or_none, maybe

log = logging.root


class JouleLanguageServer(LanguageServer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def set_workspace_root(self, root_path: str, root_uri: URI):
        self.workspace.add_folder(L.WorkspaceFolder(root_path, root_uri))
        self.workspace_index = WorkspaceIndex(root_uri)


server = JouleLanguageServer("joule", "v0.1")


@server.feature(L.INITIALIZE)
def initialize(ls: JouleLanguageServer, params: L.InitializeParams):
    for root_path in maybe(params.root_path):
        for root_uri in maybe(params.root_uri):
            log.info("Discovered workspace root: %s, %s", root_path, root_uri)

            root = Path.from_uri(root_uri).absolute()
            assert root.as_posix() == Path(root_path).absolute().as_posix()

            ls.set_workspace_root(root.as_posix(), root.as_uri())

    return L.InitializeResult(
        capabilities=L.ServerCapabilities(
            definition_provider=True,
            document_symbol_provider=True,
            document_highlight_provider=True,
            hover_provider=True,
            inlay_hint_provider=True,
            references_provider=True,
            text_document_sync=L.TextDocumentSyncKind.Full,
            workspace_symbol_provider=True,
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
        root = Path.from_uri(doc.uri).absolute().parent
        ls.set_workspace_root(root.as_posix(), root.as_uri())

    ls.workspace_index.load(doc.uri, doc.text)


@server.feature(L.TEXT_DOCUMENT_DID_CHANGE)
def did_change(ls: JouleLanguageServer, params: L.DidChangeTextDocumentParams):
    # TODO: Patch the AST incrementally.
    doc = ls.workspace.get_text_document(params.text_document.uri)
    ls.workspace_index.load(doc.uri, doc.source)


@server.feature(L.WORKSPACE_SYMBOL)
def workspace_symbol(ls: JouleLanguageServer, _: L.WorkspaceSymbolParams):
    def offsprings(symbol: L.DocumentSymbol) -> Iterator[L.DocumentSymbol]:
        return iter(
            offspring
            for children in maybe(symbol.children)
            for child in children
            for offspring in chain([child], offsprings(child))
        )

    return [
        L.WorkspaceSymbol(
            location=L.Location(doc.uri, symbol.range),
            name=symbol.name,
            kind=symbol.kind,
        )
        for doc in ls.workspace_index.docs.values()
        for top_level_symbol in doc.document_symbols
        for symbol in offsprings(top_level_symbol)
    ]


@server.feature(L.TEXT_DOCUMENT_DOCUMENT_SYMBOL)
def document_symbol(ls: JouleLanguageServer, params: L.DocumentColorParams):
    doc = ls.workspace.get_text_document(params.text_document.uri)
    return ls.workspace_index.get_or_load(doc.uri, doc.source).document_symbols


@server.feature(L.TEXT_DOCUMENT_DEFINITION)
def definition(ls: JouleLanguageServer, params: L.DefinitionParams):
    return ls.workspace_index.definitions(params.text_document.uri, params.position)


@server.feature(L.TEXT_DOCUMENT_REFERENCES)
def references(ls: JouleLanguageServer, params: L.ReferenceParams):
    return ls.workspace_index.references(params.text_document.uri, params.position)


@server.feature(L.TEXT_DOCUMENT_DOCUMENT_HIGHLIGHT)
def document_highlight(ls: JouleLanguageServer, params: L.DocumentHighlightParams):
    doc = ls.workspace.get_text_document(params.text_document.uri)
    doc_index = ls.workspace_index.get_or_load(doc.uri, doc.source)
    return doc_index.highlight(params.position)


@server.feature(L.TEXT_DOCUMENT_INLAY_HINT)
def inlay_hint(ls: JouleLanguageServer, params: L.InlayHintParams):
    doc = ls.workspace.get_text_document(params.text_document.uri)
    doc_index = ls.workspace_index.get_or_load(doc.uri, doc.source)
    return list(doc_index.inlay_hints.values())


@server.feature(L.TEXT_DOCUMENT_DOCUMENT_LINK)
def document_link(ls: JouleLanguageServer, params: L.DocumentLinkParams):
    doc = ls.workspace.get_text_document(params.text_document.uri)
    doc_index = ls.workspace_index.get_or_load(doc.uri, doc.source)
    return doc_index.links


@server.feature(L.TEXT_DOCUMENT_HOVER)
def hover(ls: JouleLanguageServer, params: L.HoverParams):
    doc = ls.workspace.get_text_document(params.text_document.uri)
    doc_index = ls.workspace_index.get_or_load(doc.uri, doc.source)
    return head_or_none(
        hover
        for key, hover in doc_index.hovers.items()
        if location_contains(key.location, params.position)
    )
