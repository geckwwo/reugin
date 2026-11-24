"""ASGI-level behaviour the TestClient can't show: clients leaving early, backpressure, cancellation."""

import asyncio
import contextlib
import unittest
from collections.abc import AsyncIterator

from reugin import Request, Response, Reugin, StreamingResponse, WebSocket
from reugin.types import Message, Scope
from reugin.websocket import MAX_QUEUED


def scope(kind: str, path: str, method: str = "GET") -> Scope:
    return {"type": kind, "method": method, "path": path, "query_string": b"", "headers": [], "root_path": ""}


async def forever() -> Message:
    await asyncio.Event().wait()
    raise AssertionError("unreachable")


class HTTPDisconnectTest(unittest.IsolatedAsyncioTestCase):
    async def test_a_cut_off_upload_never_reaches_the_handler(self) -> None:
        app = Reugin()
        bodies: list[bytes] = []

        @app.post("/upload")
        async def upload(req: Request) -> str:
            bodies.append(req.body)
            return "saved"

        incoming: list[Message] = [
            {"type": "http.request", "body": b"only the first part", "more_body": True},
            {"type": "http.disconnect"},
        ]
        sent: list[Message] = []

        async def receive() -> Message:
            return incoming.pop(0)

        async def send(message: Message) -> None:
            sent.append(message)

        await app(scope("http", "/upload", "POST"), receive, send)
        self.assertEqual((bodies, sent), ([], []))

    async def test_an_endless_stream_stops_when_the_client_leaves(self) -> None:
        app = Reugin()
        stopped = asyncio.Event()
        left = asyncio.Event()

        @app.get("/events")
        async def events(req: Request) -> Response:
            async def ticks() -> AsyncIterator[str]:
                try:
                    n = 0
                    while True:
                        yield f"tick {n}\n"
                        n += 1
                        await asyncio.sleep(0)
                finally:
                    stopped.set()

            return StreamingResponse(ticks(), content_type="text/event-stream")

        incoming: list[Message] = [{"type": "http.request", "body": b""}]
        chunks: list[bytes] = []

        async def receive() -> Message:
            if incoming:
                return incoming.pop(0)
            await left.wait()
            return {"type": "http.disconnect"}

        async def send(message: Message) -> None:
            if message["type"] == "http.response.body":
                chunks.append(message["body"])
                if len(chunks) == 5:
                    left.set()

        await asyncio.wait_for(app(scope("http", "/events"), receive, send), 2)
        self.assertTrue(stopped.is_set())
        self.assertLess(len(chunks), 50)


class WebSocketProtocolTest(unittest.IsolatedAsyncioTestCase):
    async def test_a_slow_handler_slows_the_client_down(self) -> None:
        app = Reugin()

        @app.websocket("/slow")
        async def slow(ws: WebSocket) -> None:
            await ws.accept()
            await asyncio.sleep(0.1)  # not reading

        calls = 0

        async def receive() -> Message:
            nonlocal calls
            calls += 1
            if calls == 1:
                return {"type": "websocket.connect"}
            await asyncio.sleep(0)
            return {"type": "websocket.receive", "text": "x" * 1000}

        async def send(message: Message) -> None:
            pass

        await asyncio.wait_for(app(scope("websocket", "/slow"), receive, send), 2)
        self.assertLessEqual(calls, MAX_QUEUED + 3)

    async def test_cancelling_the_app_stops_the_handler(self) -> None:
        app = Reugin()
        stopped = asyncio.Event()
        started = asyncio.Event()

        @app.websocket("/long")
        async def long(ws: WebSocket) -> None:
            await ws.accept()
            started.set()
            try:
                await asyncio.sleep(10)
            finally:
                stopped.set()

        incoming: list[Message] = [{"type": "websocket.connect"}]

        async def receive() -> Message:
            return incoming.pop(0) if incoming else await forever()

        async def send(message: Message) -> None:
            pass

        task = asyncio.create_task(app(scope("websocket", "/long"), receive, send))
        await asyncio.wait_for(started.wait(), 2)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        self.assertTrue(stopped.is_set())

    async def test_two_first_sends_accept_once(self) -> None:
        app = Reugin()

        @app.websocket("/both")
        async def both(ws: WebSocket) -> None:
            await asyncio.gather(ws.send("one"), ws.send("two"))

        incoming: list[Message] = [{"type": "websocket.connect"}]
        sent: list[str] = []

        async def receive() -> Message:
            return incoming.pop(0) if incoming else await forever()

        async def send(message: Message) -> None:
            sent.append(message["type"])
            await asyncio.sleep(0)  # a server whose send yields

        await asyncio.wait_for(app(scope("websocket", "/both"), receive, send), 2)
        self.assertEqual(sent.count("websocket.accept"), 1)
        self.assertEqual(sent.count("websocket.send"), 2)
