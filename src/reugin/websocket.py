from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from .errors import HTTPError
from .request import Connection
from .types import JSON, Message, Receive, Scope, Send

if TYPE_CHECKING:
    from .app import Reugin

logger = logging.getLogger("reugin")

MAX_QUEUED = 32
"""Incoming messages kept for a handler that isn't reading yet."""

type WebSocketHandler = Callable[..., Awaitable[object]]
"""`async def handler(ws: WebSocket, **params) -> None`"""


class WebSocketClosed(Exception):
    """The connection is closed: raised by `recv()` once every message is read, and by `send()`."""

    def __init__(self, code: int) -> None:
        super().__init__(code)
        self.code = code


class WebSocket(Connection):
    """A WebSocket connection, as a handler gets it.

    It's accepted on the first `recv()` or `send()`, or by `accept()`. A handler that raises HTTPError
    before that turns the connection down. `async for message in ws` reads until the client leaves.
    """

    def __init__(self, scope: Scope, app: Reugin, send: Send, path_params: dict[str, object] | None = None) -> None:
        super().__init__(scope, app, path_params)
        self.accepted = False
        self.close_code: int | None = None
        """Set once the connection is closed, by either side."""
        self._send = send
        # Bounded, so a client can't pile up messages faster than the handler reads them.
        self._messages: asyncio.Queue[str | bytes] = asyncio.Queue(MAX_QUEUED)
        self._closed = asyncio.Event()

    @property
    def closed(self) -> bool:
        return self.close_code is not None

    async def accept(self, subprotocol: str | None = None) -> None:
        if self.accepted or self.closed:
            return
        self.accepted = True  # before sending, so two first calls at once don't both accept
        message: dict[str, object] = {"type": "websocket.accept"}
        if subprotocol:
            message["subprotocol"] = subprotocol
        await self._send(message)

    async def recv(self) -> str | bytes:
        """The next message from the client. Raises WebSocketClosed after the last one."""
        await self.accept()
        if not self._messages.empty():
            return self._messages.get_nowait()
        if self.closed:
            raise WebSocketClosed(self.close_code or 1005)
        get = asyncio.ensure_future(self._messages.get())
        closed = asyncio.ensure_future(self._closed.wait())
        try:
            await asyncio.wait({get, closed}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            closed.cancel()
            if not get.done():
                get.cancel()
        if get.done() and not get.cancelled():
            return get.result()
        raise WebSocketClosed(self.close_code or 1005)

    async def recv_json(self) -> JSON:
        data: JSON = json.loads(await self.recv())
        return data

    async def send(self, data: str | bytes) -> None:
        if self.closed:
            raise WebSocketClosed(self.close_code or 1005)
        await self.accept()
        if isinstance(data, str):
            await self._send({"type": "websocket.send", "text": data})
        else:
            await self._send({"type": "websocket.send", "bytes": data})

    async def send_json(self, data: JSON) -> None:
        await self.send(json.dumps(data, ensure_ascii=False))

    async def close(self, code: int = 1000, reason: str = "") -> None:
        """Close the connection. Before it's accepted, this turns it down (the server answers 403)."""
        if self.closed:
            return
        self._mark_closed(code)
        reason = reason.encode()[:123].decode(errors="ignore")  # the protocol's limit is 123 bytes
        await self._send({"type": "websocket.close", "code": code, "reason": reason})

    def _mark_closed(self, code: int) -> None:
        self.close_code = code
        self._closed.set()

    def __aiter__(self) -> WebSocket:
        return self

    async def __anext__(self) -> str | bytes:
        try:
            return await self.recv()
        except WebSocketClosed:
            raise StopAsyncIteration from None

    async def run(self, handler: WebSocketHandler, receive: Receive) -> None:
        """Run `handler` while feeding it the client's messages, until either side leaves."""
        task = asyncio.create_task(self._run_handler(handler))
        incoming: asyncio.Future[Message] | None = None
        queued: asyncio.Future[None] | None = None
        try:
            while not task.done():
                incoming = asyncio.ensure_future(receive())
                await asyncio.wait({incoming, task}, return_when=asyncio.FIRST_COMPLETED)
                if not incoming.done():
                    break
                message = incoming.result()
                if message["type"] == "websocket.disconnect":
                    if not self.closed:
                        self._mark_closed(message.get("code", 1005))
                    break
                if message["type"] == "websocket.receive":
                    text: str | None = message.get("text")
                    data: str | bytes = text if text is not None else message.get("bytes", b"")
                    # Wait while the queue is full: the server stops reading, and the client slows down.
                    queued = asyncio.ensure_future(self._messages.put(data))
                    await asyncio.wait({queued, task}, return_when=asyncio.FIRST_COMPLETED)
            await task
        finally:
            # Also when this app is cancelled (a server shutting down): don't leave the handler running.
            for future in (incoming, queued, task):
                if future is not None and not future.done():
                    future.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _run_handler(self, handler: WebSocketHandler) -> None:
        try:
            await handler(self, **self.path_params)
        except WebSocketClosed:
            pass
        except HTTPError as e:
            await (self.close(1008, e.detail) if self.accepted else self.close())
        except Exception:
            logger.exception("The WebSocket handler for %s failed", self.path)
            await self.close(1011)
        await self.close()
