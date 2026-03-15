from functools import cached_property
from pathlib import Path

import lsprotocol.types as L
from pygls.lsp.server import LanguageServer

from joule.ast import URI
from joule.config import JouleConfig
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


class JouleLanguageServer(LanguageServer):
    config: JouleConfig = JouleConfig()

    @cached_property
    def loader(self) -> DocumentLoader:
        workspace_uri: URI | None = None

        match list(self.workspace.folders.keys()):
            # Two or more workspace folders, not supported
            case [_, _, *_]:
                raise RuntimeError("Joule does not support multi-workspace.")
            # Single workspace folder
            case [workspace_uri]:
                pass
            # Falls back to workspace root URI, if any
            case _ if (uri := self.workspace.root_uri) is not None:
                workspace_uri = Path.from_uri(uri).resolve().as_uri()
            # Falls back to workspace path, if any
            case _ if (workspace_path := self.workspace.root_path) is not None:
                workspace_uri = Path(workspace_path).resolve().as_uri()

        return DocumentLoader(workspace_uri, lambda: self.config)


server = JouleLanguageServer("joule", "v0.1")


@server.feature(L.INITIALIZED)
async def initialized(ls: JouleLanguageServer, _: L.InitializedParams):
    config_values = await ls.workspace_configuration_async(
        L.ConfigurationParams(
            [L.ConfigurationItem(section=field) for field in JouleConfig.model_fields]
        )
    )

    ls.config = JouleConfig(
        **{
            section: config
            for section, config in zip(JouleConfig.model_fields, config_values)
            if config is not None
        }
    )


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
    # TODO: Add progress reporting
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
