import asyncio as A
from collections.abc import Callable
from typing import Protocol, override

import lsprotocol.types as L

from joule.analysis.imports import BuildObserver


class ProgressSender(Protocol):
    """Sends the work done progress messages to the LSP client.

    The `work_done_progress` attribute of a `pygls` server implements this protocol.
    Call the methods only on the event loop.
    """

    async def create_async(self, token: str) -> object: ...

    def begin(self, token: str, value: L.WorkDoneProgressBegin) -> None: ...

    def report(self, token: str, value: L.WorkDoneProgressReport) -> None: ...

    def end(self, token: str, value: L.WorkDoneProgressEnd) -> None: ...


class FolderProgress(BuildObserver):
    """Reports the two phases of the load of one workspace folder.

    The build calls the observer methods in its own thread. Each method passes the
    message to the event loop, which owns the sender.

    The client gets an `end` for each token that `start` created, even if the build
    fails. A token that did not begin also gets an `end`.
    """

    _loop: A.AbstractEventLoop
    _sender: ProgressSender
    _name: str
    _discovery_token: str
    _graph_token: str

    # The tokens that the client created and that did not end yet. Only the event
    # loop uses it.
    _open: set[str]

    # The last percentage that Joule sent. Only the build thread uses it. The thread
    # does not post a message for each source.
    _percentage: int | None

    def __init__(
        self,
        loop: A.AbstractEventLoop,
        sender: ProgressSender,
        folder: L.WorkspaceFolder,
    ):
        self._loop = loop
        self._sender = sender
        self._name = folder.name
        self._discovery_token = f"joule/discovery/{folder.uri}"
        self._graph_token = f"joule/import-graph/{folder.uri}"
        self._open = set()
        self._percentage = None

    async def start(self) -> None:
        """Creates both tokens and begins the discovery as a spinner."""
        for token in (self._discovery_token, self._graph_token):
            await self._sender.create_async(token)
            self._open.add(token)

        self._sender.begin(
            self._discovery_token,
            L.WorkDoneProgressBegin(title=f"Discovering Jsonnet sources: {self._name}"),
        )

    async def finish(self) -> None:
        """Ends the open tokens. Call it after the build, even on errors."""
        # The build thread posts its messages before the build ends. The loop runs
        # the posted callbacks in order, so the barrier runs after the last message.
        barrier = self._loop.create_future()
        self._loop.call_soon(barrier.set_result, None)
        await barrier

        for token in (self._discovery_token, self._graph_token):
            self._end(token)

    @override
    def on_discovery_done(self, sources: int) -> None:
        self._post(self._on_discovery_done, sources)

    @override
    def on_source_collected(self, done: int, total: int) -> None:
        # The build calls this method once for each source, so the thread skips the
        # messages that do not change the integer percentage.
        percentage = done * 100 // total

        if percentage != self._percentage:
            self._percentage = percentage
            self._post(self._report, percentage, done, total)

    def _post(self, callback: Callable[..., None], *args: object) -> None:
        self._loop.call_soon_threadsafe(callback, *args)

    def _on_discovery_done(self, sources: int) -> None:
        self._end(self._discovery_token)

        self._sender.begin(
            self._graph_token,
            L.WorkDoneProgressBegin(
                title=f"Building import graph: {self._name}",
                percentage=0,
            ),
        )

        if sources == 0:
            self._end(self._graph_token, message="0 files")

    def _report(self, percentage: int, done: int, total: int) -> None:
        self._sender.report(
            self._graph_token,
            L.WorkDoneProgressReport(
                percentage=percentage,
                message=f"{done}/{total} files",
            ),
        )

    def _end(self, token: str, message: str | None = None) -> None:
        if token in self._open:
            self._open.remove(token)
            self._sender.end(token, L.WorkDoneProgressEnd(message=message))
