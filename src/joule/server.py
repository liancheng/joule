import asyncio
import uuid
from enum import IntEnum, auto
from functools import cached_property, partial
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
        Created = auto()
        Initializing = auto()
        Initialized = auto()

    state: State = State.Created

    @property
    def workspace_uri(self) -> URI:
        assert self.state in [self.State.Initializing, self.State.Initialized]

        match list(self.workspace.folders.keys()):
            case [_, _, *_]:
                raise RuntimeError("Joule does not support multi-workspace.")
            case [uri]:
                return uri
            case _ if (uri := self.workspace.root_uri) is not None:
                return Path.from_uri(uri).resolve().as_uri()
            case _ if (path := self.workspace.root_path) is not None:
                return Path(path).resolve().as_uri()
            case _:
                raise RuntimeError("No valid workspace URI detected.")

    @property
    def workspace_path(self) -> Path:
        return Path.from_uri(self.workspace_uri)

    _config: JouleConfig | None = None

    @property
    def config(self) -> JouleConfig:
        assert self.state == self.State.Initialized
        assert self._config is not None
        return self._config

    async def load_config(self) -> JouleConfig:
        assert self.state == self.State.Initializing

        items = [
            L.ConfigurationItem(section=field)
            for field in JouleConfig.model_fields.keys()
        ]

        params = L.ConfigurationParams(items)
        values = await self.workspace_configuration_async(params)

        self._config = JouleConfig(
            **{
                section: config
                for section, config in zip(JouleConfig.model_fields.keys(), values)
                if config is not None
            }
        )

        return self._config

    _document_store: DocumentStore | None = None

    @property
    def document_store(self) -> DocumentStore:
        assert self.state == self.State.Initialized
        assert self._document_store is not None
        return self._document_store

    async def load_workspace(self):
        assert self.state == self.State.Initializing
        assert self._config is not None

        self._document_store = DocumentStore(self._config, self.workspace_uri)

        progress_report_token = str(uuid.uuid4())
        await self.work_done_progress.create_async(progress_report_token)
        self.work_done_progress.begin(
            progress_report_token,
            L.WorkDoneProgressBegin(title="Loading workspace..."),
        )

        workspace_path = self.workspace_path
        paths = list(self._document_store.scan(workspace_path))
        processed = 0

        def callback(path: Path):
            nonlocal processed
            processed += 1

            self.work_done_progress.report(
                progress_report_token,
                L.WorkDoneProgressReport(
                    percentage=min(int(processed * 100.0 / len(paths)), 100),
                    message=path.relative_to(workspace_path).as_posix(),
                ),
            )

        await asyncio.to_thread(
            partial(
                self._document_store.load_workspace,
                paths=paths,
                callback=callback,
            )
        )

        self.work_done_progress.end(progress_report_token, L.WorkDoneProgressEnd())

    async def register_capabilities(self):
        assert self.state == self.State.Initializing
        assert self._config is not None

        watchers = [
            L.FileSystemWatcher(
                glob_pattern=L.RelativePattern(
                    base_uri=folder,
                    pattern=f"**/*.{{{','.join(self._config.suffixes)}}}",
                ),
                kind=L.WatchKind.Change | L.WatchKind.Create | L.WatchKind.Delete,
            )
            for folder in self.workspace.folders.values()
        ]

        registrations = [
            L.Registration(
                id=str(uuid.uuid4()),
                method=L.WORKSPACE_DID_CHANGE_WATCHED_FILES,
                register_options=L.DidChangeWatchedFilesRegistrationOptions(watchers),
            )
        ]

        await self.client_register_capability_async(L.RegistrationParams(registrations))

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
    ls.state = JouleLanguageServer.State.Initializing

    await ls.load_config()
    await ls.load_workspace()
    await ls.register_capabilities()

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
