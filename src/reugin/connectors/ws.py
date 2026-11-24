from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, override

from ..request import parse_headers, parse_query
from ..route_match import match_route
from .base import BaseConnector

if TYPE_CHECKING:
    from ..server import Reugin
    from ..types import Receive, Scope, Send

type WebSocketHandler = Callable[..., Awaitable[Any]]
"""`async def handler(ws: WebSocketConnection, *captures: str) -> None`"""


class WebSocketClosedException(Exception):
    """The connection is closed: raised by `recv()` once every message is read, and by `send()`."""

    def __init__(self, wsconn: WebSocketConnection, code: int) -> None:
        super().__init__(code)
        self.wsconn = wsconn
        self.code = code


class WebSocketConnection:
    def __init__(self, scope: Scope, send: Send) -> None:
        self.asgi_scope = scope
        self.path: str = scope["path"]
        self.params = parse_query(scope.get("query_string", b""))
        self.headers = parse_headers(scope)
        client: tuple[str, int] | list[str | int] | None = scope.get("client")
        self.addr: tuple[str, int] | None = (str(client[0]), int(client[1])) if client else None
        self.close_code: int | None = None
        """Set once the connection is closed, by either side."""
        self._send = send
        self._messages: asyncio.Queue[str | bytes | None] = asyncio.Queue()

    @property
    def closed(self) -> bool:
        return self.close_code is not None

    async def recv(self) -> str | bytes:
        """The next message from the client. Raises WebSocketClosedException after the last one."""
        message = await self._messages.get()
        if message is None:
            self._messages.put_nowait(None)  # keep raising on later calls
            raise WebSocketClosedException(self, self.close_code or 1005)
        return message

    async def send(self, data: str | bytes) -> None:
        if self.closed:
            raise WebSocketClosedException(self, self.close_code or 1005)
        if isinstance(data, str):
            await self._send({"type": "websocket.send", "text": data})
        else:
            await self._send({"type": "websocket.send", "bytes": data})

    async def close(self, code: int = 1000, reason: str = "") -> None:
        if self.closed:
            return
        self.close_code = code
        await self._send({"type": "websocket.close", "code": code, "reason": reason})
        self._messages.put_nowait(None)

    def _disconnected(self, code: int) -> None:
        if not self.closed:
            self.close_code = code
            self._messages.put_nowait(None)

    def _received(self, data: str | bytes) -> None:
        self._messages.put_nowait(data)


class WebSocketConnector(BaseConnector):
    def __init__(self) -> None:
        self.wsroutes: dict[str, WebSocketHandler] = {}

    def route[H: WebSocketHandler](self, ws_route: str) -> Callable[[H], H]:
        """Register a handler for WebSocket connections to `ws_route`."""

        def register(fn: H) -> H:
            self.wsroutes[ws_route] = fn
            return fn

        return register

    @override
    async def process_scope(self, scope: Scope, receive: Receive, send: Send, reugin: Reugin) -> bool:
        if scope["type"] != "websocket":
            return False
        handler, captures = match_route(scope["path"], self.wsroutes)
        if handler is None or captures is None:
            return False

        if (await receive())["type"] != "websocket.connect":
            return True
        await send({"type": "websocket.accept"})
        conn = WebSocketConnection(scope, send)

        async def run() -> None:
            code = 1000
            try:
                await handler(conn, *captures)
            except WebSocketClosedException:
                pass
            except Exception:
                code = 1011
                raise
            finally:
                await conn.close(code)

        task = asyncio.create_task(run())
        # Feed incoming messages to the connection until the client leaves or the handler closes it.
        while True:
            message = await receive()
            if message["type"] == "websocket.receive":
                text: str | None = message.get("text")
                conn._received(text if text is not None else message.get("bytes", b""))  # pyright: ignore[reportPrivateUsage]
            elif message["type"] == "websocket.disconnect":
                conn._disconnected(message.get("code", 1005))  # pyright: ignore[reportPrivateUsage]
                break
        await task  # re-raises the handler's error, for the error hooks
        return True
