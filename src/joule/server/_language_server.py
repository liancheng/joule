from pathlib import Path

import lsprotocol.types as L
from pygls.lsp.server import LanguageServer

from joule.config import Config
from joule.features import (
    DefinitionProvider,
    DocumentSymbolProvider,
    FoldingRangeProvider,
    ReferencesProvider,
)
from joule.maybe import maybe, optional
from joule.syntax import trees as T
from joule.workspace import resolve_document

from ._folder_service import FolderService


class JouleLanguageServer(LanguageServer):
    services: dict[str, FolderService]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.services = {}

    def find_service(self, uri: str) -> FolderService | None:
        return optional(
            service
            for folder_uri, service in sorted(self.services.items(), reverse=True)
            if Path.from_uri(uri).is_relative_to(Path.from_uri(folder_uri))
        )

    def resolve_document(self, uri: str) -> T.Document | None:
        match self.find_service(uri):
            case None:
                return resolve_document(uri)
            case service:
                return service.resolve_document(uri)


server = JouleLanguageServer("joule", "v0.0.1")


async def load_config(ls: JouleLanguageServer) -> Config:
    items = [L.ConfigurationItem(section=field) for field in Config.model_fields]
    params = L.ConfigurationParams(items)
    values = await ls.workspace_configuration_async(params)

    return Config(
        **{
            section: config
            for section, config in zip(Config.model_fields.keys(), values)
            if config is not None
        }
    )


@server.feature(L.INITIALIZED)
async def initialized(ls: JouleLanguageServer, _: L.InitializedParams):
    config = await load_config(ls)
    folders: dict[str, L.WorkspaceFolder] = ls.workspace.folders

    ls.services = {
        uri: FolderService(folder, config) for uri, folder in folders.items()
    }

    # Watch the files before the build starts. Thus the services can queue the
    # changes that occur during the build.
    await watch_files(ls)

    for service in ls.services.values():
        await service.start()


async def watch_files(ls: LanguageServer):
    supported = (
        (_ := ls.client_capabilities.workspace) is not None
        and (_ := _.did_change_watched_files) is not None
        and (_ := _.dynamic_registration) is not None
        and _
    )

    if supported:
        # Watch all files, not only sources. Files such as `.json` files are also
        # import targets.
        watcher = L.FileSystemWatcher(glob_pattern="**/*")
        options = L.DidChangeWatchedFilesRegistrationOptions(watchers=[watcher])
        registration = L.Registration(
            id="joule/watch-files",
            method=L.WORKSPACE_DID_CHANGE_WATCHED_FILES,
            register_options=options,
        )

        await ls.client_register_capability_async(L.RegistrationParams([registration]))


@server.feature(L.WORKSPACE_DID_CHANGE_WATCHED_FILES)
def did_change_watched_files(
    ls: JouleLanguageServer,
    params: L.DidChangeWatchedFilesParams,
):
    # A synchronous handler runs on the event loop without a break. Thus the events
    # change the index in the sequence that the client sends them.
    for change in params.changes:
        for service in maybe(ls.find_service(change.uri)):
            service.on_file_event(change)


@server.feature(L.TEXT_DOCUMENT_DOCUMENT_SYMBOL)
async def document_symbol(ls: JouleLanguageServer, params: L.DocumentSymbolParams):
    uri = params.text_document.uri
    return [
        symbol
        for doc in maybe(ls.resolve_document(uri))
        for symbol in DocumentSymbolProvider(doc).serve()
    ]


@server.feature(L.TEXT_DOCUMENT_DEFINITION)
async def definition(ls: JouleLanguageServer, params: L.DefinitionParams):
    uri = params.text_document.uri
    return [
        location
        for doc in maybe(ls.resolve_document(uri))
        for location in DefinitionProvider(uri, doc).serve(params.position)
    ]


@server.feature(L.TEXT_DOCUMENT_REFERENCES)
async def references(ls: JouleLanguageServer, params: L.ReferenceParams):
    uri = params.text_document.uri
    return [
        location
        for doc in maybe(ls.resolve_document(uri))
        for location in ReferencesProvider(uri, doc).serve(params.position)
    ]


@server.feature(L.TEXT_DOCUMENT_FOLDING_RANGE)
async def folding_range(ls: JouleLanguageServer, params: L.FoldingRangeParams):
    uri = params.text_document.uri
    return [
        location
        for doc in maybe(ls.resolve_document(uri))
        for location in FoldingRangeProvider().serve(doc)
    ]
