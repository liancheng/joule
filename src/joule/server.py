import asyncio
import uuid
from enum import IntEnum, auto
from functools import partial
from pathlib import Path

import lsprotocol.types as L
from pygls.lsp.server import LanguageServer

from joule.ast import URI
from joule.config import JouleConfig
from joule.maybe import head_or_none, maybe
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

    _ready: asyncio.Future | None = None

    @property
    def ready(self) -> asyncio.Future:
        assert self._ready is not None
        return self._ready

    @ready.setter
    def ready(self, value: asyncio.Future):
        self._ready = value

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
    def store(self) -> DocumentStore:
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
        paths = list(self._document_store.scan())
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


server = JouleLanguageServer("joule", "v0.1")


@server.feature(L.INITIALIZE)
async def initialize(ls: JouleLanguageServer, _: L.InitializeParams):
    ls.ready = asyncio.get_running_loop().create_future()


@server.feature(L.INITIALIZED)
async def initialized(ls: JouleLanguageServer, _: L.InitializedParams):
    ls.state = JouleLanguageServer.State.Initializing

    await ls.load_config()
    await ls.load_workspace()
    await ls.register_capabilities()

    ls.state = JouleLanguageServer.State.Initialized
    ls.ready.set_result(True)


@server.feature(L.TEXT_DOCUMENT_DID_CHANGE)
async def did_change(ls: JouleLanguageServer, params: L.DidChangeTextDocumentParams):
    await ls.ready
    doc = ls.workspace.get_text_document(params.text_document.uri)
    ls.store.update(doc.uri)


@server.feature(L.WORKSPACE_DID_CHANGE_WATCHED_FILES)
async def did_change_watched_files(
    ls: JouleLanguageServer,
    params: L.DidChangeWatchedFilesParams,
):
    await ls.ready
    for change in params.changes:
        match change.type:
            case L.FileChangeType.Changed:
                ls.store.update(change.uri)
            case L.FileChangeType.Created:
                ls.store.add(change.uri)
            case L.FileChangeType.Deleted:
                ls.store.delete(change.uri)


@server.feature(L.TEXT_DOCUMENT_DOCUMENT_SYMBOL)
async def document_symbol(ls: JouleLanguageServer, params: L.DocumentSymbolParams):
    await ls.ready
    doc = ls.workspace.get_text_document(params.text_document.uri)
    return head_or_none(
        DocumentSymbolProvider().serve(tree) for tree in maybe(ls.store.get(doc.uri))
    )


@server.feature(L.TEXT_DOCUMENT_DEFINITION)
async def definition(ls: JouleLanguageServer, params: L.DefinitionParams):
    await ls.ready
    doc = ls.workspace.get_text_document(params.text_document.uri)
    return head_or_none(
        DefinitionProvider(ls.store).serve(tree, params.position)
        for tree in maybe(ls.store.get(doc.uri))
    )


@server.feature(L.TEXT_DOCUMENT_REFERENCES)
async def references(ls: JouleLanguageServer, params: L.ReferenceParams):
    await ls.ready
    doc = ls.workspace.get_text_document(params.text_document.uri)
    return head_or_none(
        ReferencesProvider(ls.store).serve(tree, params.position)
        for tree in maybe(ls.store.get(doc.uri))
    )


@server.feature(L.TEXT_DOCUMENT_INLAY_HINT)
async def inlay_hint(ls: JouleLanguageServer, params: L.InlayHintParams):
    await ls.ready
    doc = ls.workspace.get_text_document(params.text_document.uri)
    return head_or_none(
        InlayHintProvider().serve(tree) for tree in maybe(ls.store.get(doc.uri))
    )


@server.feature(L.TEXT_DOCUMENT_DOCUMENT_HIGHLIGHT)
async def document_highlight(
    ls: JouleLanguageServer,
    params: L.DocumentHighlightParams,
):
    await ls.ready
    doc = ls.workspace.get_text_document(params.text_document.uri)
    return head_or_none(
        DocumentHighlightProvider().serve(tree, params.position)
        for tree in maybe(ls.store.get(doc.uri))
    )


@server.feature(L.TEXT_DOCUMENT_RENAME)
async def rename(ls: JouleLanguageServer, params: L.RenameParams):
    await ls.ready
    doc = ls.workspace.get_text_document(params.text_document.uri)
    return head_or_none(
        RenameProvider().serve(tree, params.position, params.new_name)
        for tree in maybe(ls.store.get(doc.uri))
    )


@server.feature(L.TEXT_DOCUMENT_PREPARE_RENAME)
async def prepare_rename(ls: JouleLanguageServer, params: L.PrepareRenameParams):
    await ls.ready
    doc = ls.workspace.get_text_document(params.text_document.uri)
    return head_or_none(
        RenameProvider().prepare(tree, params.position)
        for tree in maybe(ls.store.get(doc.uri))
    )


@server.feature(L.TEXT_DOCUMENT_FOLDING_RANGE)
async def folding_range(ls: JouleLanguageServer, params: L.FoldingRangeParams):
    await ls.ready
    doc = ls.workspace.get_text_document(params.text_document.uri)
    return head_or_none(
        FoldingRangeProvider().serve(tree) for tree in maybe(ls.store.get(doc.uri))
    )
