import lsprotocol.types as L
from pygls.lsp.server import LanguageServer

from joule.services.language_service import LanguageService


class JouleLanguageServer(LanguageServer):
    def __post_init__(self):
        self.services: dict[str, LanguageService]


server = JouleLanguageServer("joule", "v0.0.1")


@server.feature(L.INITIALIZED)
def initialized(ls: JouleLanguageServer, _: L.InitializedParams):
    folders: dict[str, L.WorkspaceFolder] = ls.workspace.folders
    ls.services = {uri: LanguageService(folder) for uri, folder in folders.items()}
