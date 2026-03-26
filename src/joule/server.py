import asyncio
import uuid
from enum import IntEnum
from functools import cached_property
from pathlib import Path

import lsprotocol.types as L
from pygls.lsp.server import LanguageServer

from joule.ast import URI
from joule.config import JouleConfig
from joule.model import DocumentLoader
from joule.model.document_store import DocumentStore
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
    class State(IntEnum):
        Created = 0
        Initialized = 1

    state: State = State.Created

    _config: JouleConfig | None = None

    @property
    def config(self) -> JouleConfig:
        assert self.state == self.State.Initialized and self._config is not None
        return self._config

    @config.setter
    def config(self, value: JouleConfig):
        self._config = value

    _document_store: DocumentStore | None = None

    @property
    def document_store(self) -> DocumentStore:
        assert self.state == self.State.Initialized and self._document_store is not None
        return self._document_store

    @document_store.setter
    def document_store(self, value: DocumentStore):
        assert self.state == self.State.Created
        self._document_store = value

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

    config = JouleConfig(
        **{
            section: config
            for section, config in zip(JouleConfig.model_fields, config_values)
            if config is not None
        }
    )

    match list(ls.workspace.folders.keys()):
        case [_, _, *_]:
            raise RuntimeError("Joule does not support multi-workspace.")
        case [uri]:
            workspace_uri = uri
        case _ if (uri := ls.workspace.root_uri) is not None:
            workspace_uri = Path.from_uri(uri).resolve().as_uri()
        case _ if (path := ls.workspace.root_path) is not None:
            workspace_uri = Path(path).resolve().as_uri()
        case _:
            raise RuntimeError("No valid workspace URI detected.")

    workspace_path = Path.from_uri(workspace_uri)
    document_store = DocumentStore(config, workspace_uri)

    token = str(uuid.uuid4())
    await ls.work_done_progress.create_async(token)

    ls.work_done_progress.begin(
        token,
        L.WorkDoneProgressBegin(title="Indexing", cancellable=True),
    )

    def load_workspace():
        def callback(path: Path):
            ls.work_done_progress.report(
                token,
                L.WorkDoneProgressReport(
                    cancellable=True,
                    message=path.relative_to(workspace_path).as_posix(),
                ),
            )

        document_store.load_workspace(callback=callback)

    await asyncio.to_thread(load_workspace)

    ls.work_done_progress.end(token, L.WorkDoneProgressEnd())

    async def register_capabilities():
        watchers = [
            L.FileSystemWatcher(
                glob_pattern=L.RelativePattern(
                    base_uri=folder,
                    pattern=f"**/*.{{{','.join(config.suffixes)}}}",
                ),
                kind=L.WatchKind.Change | L.WatchKind.Create | L.WatchKind.Delete,
            )
            for folder in ls.workspace.folders.values()
        ]

        registration = L.Registration(
            id=str(uuid.uuid4()),
            method=L.WORKSPACE_DID_CHANGE_WATCHED_FILES,
            register_options=L.DidChangeWatchedFilesRegistrationOptions(watchers),
        )

        await ls.client_register_capability_async(L.RegistrationParams([registration]))

    await register_capabilities()

    ls.config = config
    ls.document_store = document_store
    ls.state = JouleLanguageServer.State.Initialized


@server.feature(L.TEXT_DOCUMENT_DID_OPEN)
def did_open(ls: JouleLanguageServer, params: L.DidOpenTextDocumentParams):
    doc = params.text_document
    ls.loader.load_and_cache_from_source(doc.uri, doc.text)


@server.feature(L.TEXT_DOCUMENT_DID_CHANGE)
def did_change(ls: JouleLanguageServer, params: L.DidChangeTextDocumentParams):
    doc = ls.workspace.get_text_document(params.text_document.uri)
    ls.loader.load_and_cache_from_source(doc.uri, doc.source)


@server.feature(L.WORKSPACE_DID_CHANGE_WATCHED_FILES)
def did_change_watched_files(
    ls: JouleLanguageServer,
    params: L.DidChangeWatchedFilesParams,
):
    for change in params.changes:
        ls.window_log_message(L.LogMessageParams(L.MessageType.Info, f"{change}"))


@server.feature(L.TEXT_DOCUMENT_DOCUMENT_SYMBOL)
def document_symbol(ls: JouleLanguageServer, params: L.DocumentSymbolParams):
    doc = ls.workspace.get_text_document(params.text_document.uri)
    return (
        DocumentSymbolProvider().serve(tree)
        if (tree := ls.loader.from_source(doc.uri, doc.source))
        else None
    )


@server.feature(L.TEXT_DOCUMENT_DEFINITION)
def definition(ls: JouleLanguageServer, params: L.DefinitionParams):
    doc = ls.workspace.get_text_document(params.text_document.uri)
    return (
        DefinitionProvider(ls.loader).serve(tree, params.position)
        if (tree := ls.loader.from_source(doc.uri, doc.source))
        else None
    )


@server.feature(L.TEXT_DOCUMENT_REFERENCES)
def references(ls: JouleLanguageServer, params: L.ReferenceParams):
    # TODO: Add progress reporting
    doc = ls.workspace.get_text_document(params.text_document.uri)
    return (
        ReferencesProvider(ls.loader).serve(tree, params.position)
        if (tree := ls.loader.from_source(doc.uri, doc.source))
        else None
    )


@server.feature(L.TEXT_DOCUMENT_INLAY_HINT)
def inlay_hint(ls: JouleLanguageServer, params: L.InlayHintParams):
    doc = ls.workspace.get_text_document(params.text_document.uri)
    return (
        InlayHintProvider().serve(tree)
        if (tree := ls.loader.from_source(doc.uri, doc.source))
        else None
    )


@server.feature(L.TEXT_DOCUMENT_DOCUMENT_HIGHLIGHT)
def document_highlight(ls: JouleLanguageServer, params: L.DocumentHighlightParams):
    doc = ls.workspace.get_text_document(params.text_document.uri)
    return (
        DocumentHighlightProvider().serve(tree, params.position)
        if (tree := ls.loader.from_source(doc.uri, doc.source))
        else None
    )


@server.feature(L.TEXT_DOCUMENT_RENAME)
def rename(ls: JouleLanguageServer, params: L.RenameParams):
    doc = ls.workspace.get_text_document(params.text_document.uri)
    return (
        RenameProvider().serve(tree, params.position, params.new_name)
        if (tree := ls.loader.from_source(doc.uri, doc.source))
        else None
    )


@server.feature(L.TEXT_DOCUMENT_PREPARE_RENAME)
def prepare_rename(ls: JouleLanguageServer, params: L.PrepareRenameParams):
    doc = ls.workspace.get_text_document(params.text_document.uri)
    return (
        RenameProvider().prepare(tree, params.position)
        if (tree := ls.loader.from_source(doc.uri, doc.source))
        else None
    )


@server.feature(L.TEXT_DOCUMENT_FOLDING_RANGE)
def folding_range(ls: JouleLanguageServer, params: L.FoldingRangeParams):
    doc = ls.workspace.get_text_document(params.text_document.uri)
    return (
        FoldingRangeProvider().serve(tree)
        if (tree := ls.loader.from_source(doc.uri, doc.source))
        else None
    )
