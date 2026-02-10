import logging
from pathlib import Path

import lsprotocol.types as L
from pygls.lsp.server import LanguageServer

from joule.ast import URI, Document
from joule.model import ScopeResolver
from joule.parsing import parse_jsonnet
from joule.providers import (
    DefinitionProvider,
    DocumentSymbolProvider,
    ReferencesProvider,
)
from joule.providers.inlay_hint_provider import InlayHintProvider
from joule.util import maybe

log = logging.root


class JouleLanguageServer(LanguageServer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def set_workspace_root(self, root_path: str, root_uri: URI):
        self.workspace.add_folder(L.WorkspaceFolder(root_path, root_uri))
        self.trees: dict[URI, Document] = {}

    def load(self, uri: URI, source: str, refresh: bool = False) -> Document:
        if uri not in self.trees or refresh:
            cst = parse_jsonnet(source)
            ast = Document.from_cst(uri, cst)
            self.trees[uri] = ScopeResolver().resolve(ast)

        return self.trees[uri]


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
        root = Path.from_uri(doc.uri).absolute().parent
        ls.set_workspace_root(root.as_posix(), root.as_uri())

    ls.load(doc.uri, doc.text)


@server.feature(L.TEXT_DOCUMENT_DID_CHANGE)
def did_change(ls: JouleLanguageServer, params: L.DidChangeTextDocumentParams):
    doc = ls.workspace.get_text_document(params.text_document.uri)
    ls.load(doc.uri, doc.source, refresh=True)


@server.feature(L.TEXT_DOCUMENT_DOCUMENT_SYMBOL)
def document_symbol(ls: JouleLanguageServer, params: L.DocumentSymbolParams):
    doc = ls.workspace.get_text_document(params.text_document.uri)
    tree = ls.load(doc.uri, doc.source)
    return DocumentSymbolProvider().serve(tree)


@server.feature(L.TEXT_DOCUMENT_DEFINITION)
def definition(ls: JouleLanguageServer, params: L.DefinitionParams):
    doc = ls.workspace.get_text_document(params.text_document.uri)
    tree = ls.load(doc.uri, doc.source)
    return DefinitionProvider(tree).serve(params.position)


@server.feature(L.TEXT_DOCUMENT_REFERENCES)
def references(ls: JouleLanguageServer, params: L.ReferenceParams):
    doc = ls.workspace.get_text_document(params.text_document.uri)
    tree = ls.load(doc.uri, doc.source)
    return ReferencesProvider(tree).serve(params.position)


@server.feature(L.TEXT_DOCUMENT_INLAY_HINT)
def inlay_hint(ls: JouleLanguageServer, params: L.InlayHintParams):
    doc = ls.workspace.get_text_document(params.text_document.uri)
    tree = ls.load(doc.uri, doc.source)
    return InlayHintProvider(tree).serve()
