import lsprotocol.types as L
from pygls.lsp.server import LanguageServer

from joule.analysis.scopes import resolve
from joule.config import Config
from joule.features import DefinitionProvider, DocumentSymbolProvider
from joule.maybe import head_or_none, maybe
from joule.syntax import trees as T
from joule.workspace import FolderIndex


class JouleLanguageServer(LanguageServer):
    indexes: dict[str, FolderIndex]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.indexes = {}

    def index_for(self, uri: str) -> FolderIndex | None:
        return head_or_none(
            index
            for folder_uri, index in sorted(self.indexes.items(), reverse=True)
            if uri.startswith(folder_uri.rstrip("/") + "/")
        )


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


def resolve_document(uri: str) -> T.Document | None:
    return head_or_none(resolve(doc) for doc in maybe(T.parse_document(uri)))


@server.feature(L.INITIALIZED)
async def initialized(ls: JouleLanguageServer, _: L.InitializedParams):
    config = await load_config(ls)
    folders: dict[str, L.WorkspaceFolder] = ls.workspace.folders
    ls.indexes = {uri: FolderIndex(folder, config) for uri, folder in folders.items()}

    for index in ls.indexes.values():
        await index.start()


@server.feature(L.TEXT_DOCUMENT_DOCUMENT_SYMBOL)
async def document_symbol(_: LanguageServer, params: L.DocumentSymbolParams):
    uri = params.text_document.uri
    return [
        symbol
        for doc in maybe(resolve_document(uri))
        for symbol in DocumentSymbolProvider(doc).serve()
    ]


@server.feature(L.TEXT_DOCUMENT_DEFINITION)
async def definition(_: LanguageServer, params: L.DefinitionParams):
    uri = params.text_document.uri
    return [
        location
        for doc in maybe(resolve_document(uri))
        for location in DefinitionProvider(uri, doc).serve(params.position)
    ]
