import logging
import unittest

import reugin
from reugin.connectors import WebSocketConnection, WebSocketConnector

from .asgi import lifespan, websocket


class WebSocketTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.app = reugin.Reugin()
        ws = self.app.connect(WebSocketConnector())
        self.received: list[str | bytes] = []

        @ws.route("/echo")
        async def echo(conn: WebSocketConnection) -> None:
            while True:
                message = await conn.recv()
                self.received.append(message)
                await conn.send(message)

        @ws.route("/rooms/{alphanumeric}")
        async def room(conn: WebSocketConnection, name: str) -> None:
            await conn.send(f"welcome to {name}")
            await conn.close(4000)

        @ws.route("/broken")
        async def broken(conn: WebSocketConnection) -> None:
            raise RuntimeError("nope")

        logging.disable(logging.CRITICAL)

    def tearDown(self) -> None:
        logging.disable(logging.NOTSET)

    async def test_echo_until_the_client_leaves(self) -> None:
        session = await websocket(self.app, "/echo", ["hi", b"\x00\x01"])
        self.assertTrue(session.accepted)
        self.assertEqual(session.messages, ["hi", b"\x00\x01"])
        self.assertEqual(self.received, ["hi", b"\x00\x01"])

    async def test_handler_closes(self) -> None:
        session = await websocket(self.app, "/rooms/lobby", [], disconnect=False)
        self.assertEqual(session.messages, ["welcome to lobby"])
        self.assertEqual(session.close_code, 4000)

    async def test_handler_error_closes_with_1011(self) -> None:
        session = await websocket(self.app, "/broken", [], disconnect=False)
        self.assertEqual(session.close_code, 1011)

    async def test_unknown_route_is_refused(self) -> None:
        session = await websocket(self.app, "/nope", [], disconnect=False)
        self.assertFalse(session.accepted)
        self.assertEqual(session.close_code, 1000)


class LifespanTests(unittest.IsolatedAsyncioTestCase):
    async def test_handlers_run(self) -> None:
        app = reugin.Reugin()
        calls: list[str] = []

        @app.on_startup
        async def start() -> None:
            calls.append("start")

        @app.on_shutdown
        async def stop() -> None:
            calls.append("stop")

        self.assertEqual(await lifespan(app), ["lifespan.startup.complete", "lifespan.shutdown.complete"])
        self.assertEqual(calls, ["start", "stop"])

    async def test_failed_startup(self) -> None:
        app = reugin.Reugin()

        @app.on_startup
        async def start() -> None:
            raise RuntimeError("no database")

        logging.disable(logging.CRITICAL)
        try:
            self.assertEqual(await lifespan(app), ["lifespan.startup.failed"])
        finally:
            logging.disable(logging.NOTSET)


if __name__ == "__main__":
    unittest.main()
