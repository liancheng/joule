import lsprotocol.types as L
from pygls.lsp.server import LanguageServer

from joule import trees as T
from joule.maybe import head_or_none, maybe
from joule.providers import (
    DefinitionProvider,
    DocumentSymbolProvider,
    ScopeResolver,
    WorkspaceService,
)


def resolve_document(uri: str) -> T.Document | None:
    if (doc := T.parse_document(uri)) is not None:
        ScopeResolver(doc)
        return doc

    return None


class JouleLanguageServer(LanguageServer):
    services: dict[str, WorkspaceService]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.services = {}

    def get_workspace_service(self, uri: str) -> WorkspaceService | None:
        return head_or_none(
            service
            for folder_uri, service in sorted(self.services.items(), reverse=True)
            if uri.startswith(folder_uri.rstrip("/") + "/")
        )


server = JouleLanguageServer("joule", "v0.0.1")


@server.feature(L.INITIALIZED)
async def initialized(ls: JouleLanguageServer, _: L.InitializedParams):
    folders: dict[str, L.WorkspaceFolder] = ls.workspace.folders
    ls.services = {uri: WorkspaceService(folder) for uri, folder in folders.items()}

    for service in ls.services.values():
        await service.start()


@server.feature(L.TEXT_DOCUMENT_DOCUMENT_SYMBOL)
async def document_symbol(_: JouleLanguageServer, params: L.DocumentSymbolParams):
    uri = params.text_document.uri
    return [
        symbol
        for doc in maybe(resolve_document(uri))
        for symbol in DocumentSymbolProvider(doc).serve()
    ]


@server.feature(L.TEXT_DOCUMENT_DEFINITION)
async def definition(_: JouleLanguageServer, params: L.DefinitionParams):
    uri = params.text_document.uri
    return [
        location
        for doc in maybe(resolve_document(uri))
        for location in DefinitionProvider(uri, doc).serve(params.position)
    ]
