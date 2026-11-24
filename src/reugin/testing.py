"""Drive an ASGI app in tests, without a server.

    async with TestClient(app) as client:  # runs startup and shutdown handlers
        res = await client.get("/notes/1")
        assert res.status == 200

        async with client.websocket("/chat") as ws:
            await ws.send("hi")
            assert await ws.recv() == "hi"

The client keeps the cookies the app sets and sends them back.
"""

import asyncio
import json as jsonlib
from collections.abc import Mapping
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Self
from urllib.parse import unquote, urlencode

from .response import HeaderInput, header_pairs
from .rpc import RPCFunction
from .types import JSON, ASGIApp, Message, Receive, Scope, Send
from .websocket import WebSocketClosed

TIMEOUT = 5.0


class _Missing:
    pass


MISSING = _Missing()


@dataclass
class Result:
    """What the app answered."""

    __test__ = False

    status: int
    headers: list[tuple[str, str]]
    """Lowercase names, in the order sent; a name can repeat."""
    body: bytes

    def header(self, name: str) -> str | None:
        return next((value for key, value in self.headers if key == name.lower()), None)

    @property
    def text(self) -> str:
        return self.body.decode()

    def json(self) -> JSON:
        data: JSON = jsonlib.loads(self.body)
        return data


def _scope(kind: str, path: str, headers: list[tuple[str, str]]) -> Scope:
    path, _, query = path.partition("?")
    return {
        "type": kind,
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "scheme": "http" if kind == "http" else "ws",
        "path": unquote(path),
        "raw_path": path.encode(),
        "query_string": query.encode(),
        "root_path": "",
        "headers": [(name.lower().encode("latin-1"), value.encode("latin-1")) for name, value in headers],
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
    }


async def _run(app: ASGIApp, scope: Scope, receive: Receive, send: Send) -> None:
    await app(scope, receive, send)


async def _wait(get: asyncio.Future[Message], task: asyncio.Task[None]) -> Message:
    """The next message from the app, or the app's own exception if it fails first."""
    await asyncio.wait({get, task}, timeout=TIMEOUT, return_when=asyncio.FIRST_COMPLETED)
    if get.done():
        return get.result()
    get.cancel()
    if task.done():
        task.result()
        raise RuntimeError("the app finished without answering")
    raise TimeoutError(f"the app didn't answer within {TIMEOUT} seconds")


class TestWebSocket:
    """The client side of a WebSocket connection. Use `client.websocket(path)`."""

    __test__ = False

    def __init__(self, app: ASGIApp, scope: Scope) -> None:
        self.app = app
        self.scope = scope
        self.accepted = False
        self.close_code: int | None = None
        """Set when either side closes. Before accepting, a close means the app turned the connection down."""
        self._to_app: asyncio.Queue[Message] = asyncio.Queue()
        self._from_app: asyncio.Queue[Message] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None

    async def _app_send(self, message: Message) -> None:
        if message["type"] == "websocket.close":
            self._to_app.put_nowait({"type": "websocket.disconnect", "code": message.get("code", 1000)})
        await self._from_app.put(message)

    async def _next(self) -> Message:
        assert self._task is not None, "use `async with client.websocket(...)`"
        return await _wait(asyncio.ensure_future(self._from_app.get()), self._task)

    async def __aenter__(self) -> Self:
        self._to_app.put_nowait({"type": "websocket.connect"})
        self._task = asyncio.create_task(_run(self.app, self.scope, self._to_app.get, self._app_send))
        message = await self._next()
        if message["type"] == "websocket.accept":
            self.accepted = True
        elif message["type"] == "websocket.close":
            self.close_code = message.get("code", 1000)
        return self

    async def send(self, data: str | bytes) -> None:
        if self.close_code is not None:
            raise WebSocketClosed(self.close_code)
        key = "text" if isinstance(data, str) else "bytes"
        self._to_app.put_nowait({"type": "websocket.receive", key: data})

    async def send_json(self, data: JSON) -> None:
        await self.send(jsonlib.dumps(data))

    async def recv(self) -> str | bytes:
        """The next message from the app. Raises WebSocketClosed once the app closes the connection."""
        if self.close_code is not None and self._from_app.empty():
            raise WebSocketClosed(self.close_code)
        message = await self._next()
        if message["type"] == "websocket.close":
            code: int = message.get("code", 1000)
            self.close_code = code
            raise WebSocketClosed(code)
        text: str | None = message.get("text")
        return text if text is not None else message.get("bytes", b"")

    async def recv_json(self) -> JSON:
        data: JSON = jsonlib.loads(await self.recv())
        return data

    async def close(self, code: int = 1000) -> None:
        if self.close_code is None:
            self.close_code = code
            self._to_app.put_nowait({"type": "websocket.disconnect", "code": code})

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        await self.close()
        if self._task is not None:
            await asyncio.wait_for(self._task, TIMEOUT)


class TestClient:
    __test__ = False

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.cookies: dict[str, str] = {}
        """Cookies the app has set, sent back with every request (as they were sent, percent-encoded)."""
        self._lifespan: tuple[asyncio.Queue[Message], asyncio.Queue[Message], asyncio.Task[None]] | None = None

    async def __aenter__(self) -> Self:
        """Run the app's startup handlers. Raises RuntimeError if one fails."""
        incoming: asyncio.Queue[Message] = asyncio.Queue()
        outgoing: asyncio.Queue[Message] = asyncio.Queue()
        scope: Scope = {"type": "lifespan", "asgi": {"version": "3.0"}}
        task = asyncio.create_task(_run(self.app, scope, incoming.get, outgoing.put))
        self._lifespan = incoming, outgoing, task
        incoming.put_nowait({"type": "lifespan.startup"})
        message = await _wait(asyncio.ensure_future(outgoing.get()), task)
        if message["type"] != "lifespan.startup.complete":
            raise RuntimeError(f"startup failed: {message.get('message', '')}")
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        if self._lifespan is None:
            return
        incoming, outgoing, task = self._lifespan
        self._lifespan = None
        incoming.put_nowait({"type": "lifespan.shutdown"})
        message = await _wait(asyncio.ensure_future(outgoing.get()), task)
        await asyncio.wait_for(task, TIMEOUT)
        if message["type"] != "lifespan.shutdown.complete":
            raise RuntimeError(f"shutdown failed: {message.get('message', '')}")

    def _headers(self, headers: HeaderInput) -> list[tuple[str, str]]:
        pairs = header_pairs(headers)
        if self.cookies and not any(name == "cookie" for name, _ in pairs):
            pairs.append(("cookie", "; ".join(f"{name}={value}" for name, value in self.cookies.items())))
        return pairs

    def _keep_cookies(self, result: Result) -> None:
        for name, value in result.headers:
            if name != "set-cookie":
                continue
            pair, *attributes = value.split(";")
            cookie, _, cookie_value = pair.strip().partition("=")
            if any(a.strip().lower() == "max-age=0" for a in attributes):
                self.cookies.pop(cookie, None)
            else:
                self.cookies[cookie] = cookie_value

    async def request(
        self,
        method: str,
        path: str,
        *,
        headers: HeaderInput = None,
        body: bytes | str = b"",
        json: JSON | _Missing = MISSING,
        form: Mapping[str, str] | None = None,
        chunk_size: int | None = None,
    ) -> Result:
        """Send one request. `path` may have a query string. `json` and `form` set the body and its
        Content-Type. `chunk_size` splits the body into several messages, as a server might.
        """
        header_list = self._headers(headers)
        if not isinstance(json, _Missing):
            body = jsonlib.dumps(json)
            header_list.append(("content-type", "application/json"))
        elif form is not None:
            body = urlencode(form)
            header_list.append(("content-type", "application/x-www-form-urlencoded"))
        data = body.encode() if isinstance(body, str) else body
        size = chunk_size or max(1, len(data))
        pieces = [data[i : i + size] for i in range(0, len(data), size)] or [b""]
        incoming: list[Message] = [
            {"type": "http.request", "body": piece, "more_body": i < len(pieces) - 1} for i, piece in enumerate(pieces)
        ]
        sent: list[Message] = []
        finished = asyncio.Event()

        async def receive() -> Message:
            if incoming:
                return incoming.pop(0)
            await finished.wait()  # like a server: the client is still there until the response is done
            return {"type": "http.disconnect"}

        async def send(message: Message) -> None:
            sent.append(message)
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                finished.set()

        scope = _scope("http", path, header_list)
        scope["method"] = method.upper()
        await asyncio.wait_for(self.app(scope, receive, send), TIMEOUT)
        start, *body_messages = sent
        raw_headers: list[tuple[bytes, bytes]] = start["headers"]
        result = Result(
            start["status"],
            [(name.decode("latin-1"), value.decode("latin-1")) for name, value in raw_headers],
            b"".join(message.get("body", b"") for message in body_messages),
        )
        self._keep_cookies(result)
        return result

    async def get(self, path: str, **kwargs: Any) -> Result:
        return await self.request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs: Any) -> Result:
        return await self.request("POST", path, **kwargs)

    async def put(self, path: str, **kwargs: Any) -> Result:
        return await self.request("PUT", path, **kwargs)

    async def patch(self, path: str, **kwargs: Any) -> Result:
        return await self.request("PATCH", path, **kwargs)

    async def delete(self, path: str, **kwargs: Any) -> Result:
        return await self.request("DELETE", path, **kwargs)

    async def rpc(self, fn: RPCFunction[..., Any], *args: JSON) -> Result:
        """Call an `@app.rpc` function the way the browser does."""
        return await self.request("POST", fn.url, json=list(args))

    def websocket(self, path: str, *, headers: HeaderInput = None) -> TestWebSocket:
        return TestWebSocket(self.app, _scope("websocket", path, self._headers(headers)))
