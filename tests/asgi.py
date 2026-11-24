"""A minimal stand-in for an ASGI server, enough to drive a Reugin app in tests."""

import asyncio
import json
from collections.abc import Iterable
from dataclasses import dataclass, field

from reugin import Reugin
from reugin.types import JSON, Message, Scope


@dataclass
class Result:
    status: int
    headers: dict[str, str]
    body: bytes

    @property
    def text(self) -> str:
        return self.body.decode()

    def json(self) -> JSON:
        data: JSON = json.loads(self.body)
        return data


async def request(
    app: Reugin,
    method: str,
    path: str,
    *,
    query: str = "",
    body: bytes = b"",
    headers: Iterable[tuple[str, str]] = (),
    chunk: int | None = None,
) -> Result:
    """Send one HTTP request. `chunk` splits the body into several http.request messages."""
    size = chunk or max(1, len(body))
    pieces = [body[i : i + size] for i in range(0, len(body), size)] or [b""]
    incoming: list[Message] = [
        {"type": "http.request", "body": piece, "more_body": i < len(pieces) - 1} for i, piece in enumerate(pieces)
    ]
    sent: list[Message] = []

    async def receive() -> Message:
        return incoming.pop(0) if incoming else {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        sent.append(message)

    scope: Scope = {
        "type": "http",
        "method": method,
        "path": path,
        "query_string": query.encode(),
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers],
        "client": ("127.0.0.1", 50000),
    }
    await app(scope, receive, send)
    start, end = sent[0], sent[1]
    raw_headers: list[tuple[bytes, bytes]] = start["headers"]
    return Result(start["status"], {k.decode(): v.decode() for k, v in raw_headers}, end["body"])


@dataclass
class WebSocketSession:
    """What the app sent during a WebSocket session."""

    sent: list[Message] = field(default_factory=list[Message])

    @property
    def accepted(self) -> bool:
        return any(m["type"] == "websocket.accept" for m in self.sent)

    @property
    def messages(self) -> list[str | bytes]:
        return [m.get("text") or m.get("bytes", b"") for m in self.sent if m["type"] == "websocket.send"]

    @property
    def close_code(self) -> int | None:
        codes = [m.get("code", 1000) for m in self.sent if m["type"] == "websocket.close"]
        return codes[0] if codes else None


async def websocket(
    app: Reugin, path: str, messages: Iterable[str | bytes], *, disconnect: bool = True
) -> WebSocketSession:
    """Connect, send `messages`, then disconnect (or wait for the app to close the connection)."""
    session = WebSocketSession()
    incoming: asyncio.Queue[Message] = asyncio.Queue()
    incoming.put_nowait({"type": "websocket.connect"})
    for m in messages:
        incoming.put_nowait(
            {"type": "websocket.receive", "text": m}
            if isinstance(m, str)
            else {"type": "websocket.receive", "bytes": m}
        )

    async def receive() -> Message:
        if incoming.empty() and disconnect:
            await asyncio.sleep(0.01)  # let the handler answer first
            if incoming.empty():
                return {"type": "websocket.disconnect", "code": 1000}
        return await incoming.get()

    async def send(message: Message) -> None:
        session.sent.append(message)
        if message["type"] == "websocket.close":
            incoming.put_nowait({"type": "websocket.disconnect", "code": message.get("code", 1000)})

    scope: Scope = {
        "type": "websocket",
        "path": path,
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 50000),
    }
    await asyncio.wait_for(app(scope, receive, send), timeout=2)
    return session


async def lifespan(app: Reugin) -> list[str]:
    """Run startup then shutdown, and return the message types the app sent."""
    incoming: list[Message] = [{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}]
    sent: list[str] = []

    async def receive() -> Message:
        return incoming.pop(0)

    async def send(message: Message) -> None:
        sent.append(message["type"])
        if message["type"].endswith("failed"):
            incoming.clear()

    await app({"type": "lifespan"}, receive, send)
    return sent
