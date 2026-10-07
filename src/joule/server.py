import lsprotocol.types as L
from pygls.lsp.server import LanguageServer

from joule.maybe import head_or_none, maybe
from joule.providers import DocumentSymbolProvider, WorkspaceService


class JouleLanguageServer(LanguageServer):
    services: dict[str, WorkspaceService]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.services = {}

    def service_for(self, doc_uri: str) -> WorkspaceService | None:
        return head_or_none(
            service
            for folder_uri, service in sorted(self.services.items(), reverse=True)
            if doc_uri.startswith(folder_uri.rstrip("/") + "/")
        )


server = JouleLanguageServer("joule", "v0.0.1")


@server.feature(L.INITIALIZED)
async def initialized(ls: JouleLanguageServer, _: L.InitializedParams):
    folders: dict[str, L.WorkspaceFolder] = ls.workspace.folders
    ls.services = {uri: WorkspaceService(folder) for uri, folder in folders.items()}

    for service in ls.services.values():
        await service.start()


@server.feature(L.TEXT_DOCUMENT_DOCUMENT_SYMBOL)
async def document_symbol(ls: JouleLanguageServer, params: L.DocumentSymbolParams):
    uri = params.text_document.uri
    return [
        symbol
        for service in maybe(ls.service_for(uri))
        for doc in maybe(service.document_for(uri))
        for symbol in DocumentSymbolProvider(doc).serve()
    ]
