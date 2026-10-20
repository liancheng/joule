import lsprotocol.types as L
from pygls.lsp.server import LanguageServer

from joule.config import Config
from joule.features import (
    DefinitionProvider,
    DocumentSymbolProvider,
    FoldingRangeProvider,
    ReferencesProvider,
)
from joule.maybe import head_or_none, maybe
from joule.syntax import trees as T
from joule.workspace import resolve_document

from ._folder_service import FolderService


class JouleLanguageServer(LanguageServer):
    services: dict[str, FolderService]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.services = {}

    def find_service(self, uri: str) -> FolderService | None:
        return head_or_none(
            service
            for folder_uri, service in sorted(self.services.items(), reverse=True)
            if uri.startswith(folder_uri.rstrip("/") + "/")
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

    for service in ls.services.values():
        await service.start()


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
