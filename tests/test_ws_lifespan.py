import unittest

from reugin import HTTPError, Request, Reugin, WebSocket, WebSocketClosed
from reugin.testing import TestClient


def make_app() -> Reugin:
    app = Reugin()

    @app.websocket("/echo")
    async def echo(ws: WebSocket) -> None:
        async for message in ws:
            await ws.send(message)

    @app.get("/echo")
    async def echo_page(req: Request) -> str:
        return "a page on the same path"

    @app.websocket("/rooms/{room}")
    async def room(ws: WebSocket, room: str) -> None:
        await ws.send_json({"room": room})
        await ws.send_json({"got": await ws.recv_json()})
        await ws.close(4000)

    @app.websocket("/private")
    async def private(ws: WebSocket) -> None:
        if ws.query.get("token") != "yes":
            raise HTTPError(403)
        await ws.send("welcome")

    @app.websocket("/broken")
    async def broken(ws: WebSocket) -> None:
        await ws.recv()
        raise RuntimeError("broken")

    return app


class WebSocketTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.client = TestClient(make_app())

    async def test_echo(self) -> None:
        async with self.client.websocket("/echo") as ws:
            self.assertTrue(ws.accepted)
            await ws.send("hi")
            await ws.send(b"\x00\x01")
            self.assertEqual(await ws.recv(), "hi")
            self.assertEqual(await ws.recv(), b"\x00\x01")
        self.assertEqual((await self.client.get("/echo")).text, "a page on the same path")

    async def test_params_json_and_close(self) -> None:
        async with self.client.websocket("/rooms/kitchen") as ws:
            self.assertEqual(await ws.recv_json(), {"room": "kitchen"})
            await ws.send_json([1, 2])
            self.assertEqual(await ws.recv_json(), {"got": [1, 2]})
            with self.assertRaises(WebSocketClosed) as caught:
                await ws.recv()
            self.assertEqual(caught.exception.code, 4000)

    async def test_turned_down_before_accepting(self) -> None:
        async with self.client.websocket("/private") as ws:
            self.assertFalse(ws.accepted)
            self.assertIsNotNone(ws.close_code)
        async with self.client.websocket("/private?token=yes") as ws:
            self.assertTrue(ws.accepted)
            self.assertEqual(await ws.recv(), "welcome")

    async def test_unknown_path(self) -> None:
        async with self.client.websocket("/nowhere") as ws:
            self.assertFalse(ws.accepted)

    async def test_handler_errors_close_with_1011(self) -> None:
        with self.assertLogs("reugin", "ERROR"):
            async with self.client.websocket("/broken") as ws:
                await ws.send("x")
                with self.assertRaises(WebSocketClosed) as caught:
                    await ws.recv()
        self.assertEqual(caught.exception.code, 1011)


class LifespanTest(unittest.IsolatedAsyncioTestCase):
    async def test_startup_shutdown_and_state(self) -> None:
        app = Reugin()
        events: list[str] = []

        @app.on_startup
        async def start() -> None:
            app.state.db = "connected"
            events.append("start")

        @app.on_shutdown
        async def stop() -> None:
            events.append("stop")

        @app.get("/db")
        async def db(req: Request) -> dict[str, str]:
            return {"db": req.app.state.db}

        async with TestClient(app) as client:
            self.assertEqual((await client.get("/db")).json(), {"db": "connected"})
            self.assertEqual(events, ["start"])
        self.assertEqual(events, ["start", "stop"])

    async def test_failing_startup(self) -> None:
        app = Reugin()

        @app.on_startup
        async def start() -> None:
            raise RuntimeError("no database")

        with self.assertLogs("reugin", "ERROR"), self.assertRaises(RuntimeError):
            async with TestClient(app):
                pass
