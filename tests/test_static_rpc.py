import logging
import tempfile
import unittest
from pathlib import Path

import reugin
from reugin.connectors import HTTPConnector, RemoteCall, RPCConnector
from reugin.mounts import StaticContent
from reugin.route_match import check_and_extract

from .asgi import request


class StaticTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        root = Path(self.dir.name)
        (root / "static" / "css").mkdir(parents=True)
        (root / "static" / "css" / "site.css").write_text("body { color: red }")
        (root / "static" / "logo.png").write_bytes(b"\x89PNG")
        (root / "static_private").mkdir()
        (root / "static_private" / "secret.txt").write_text("secret")
        self.app = reugin.Reugin()
        http = self.app.connect(HTTPConnector())
        http.get("/static/{filepath}")(StaticContent(root / "static"))
        http.get("/raw/{}")(StaticContent(root / "static"))

    def tearDown(self) -> None:
        self.dir.cleanup()

    async def test_serves_files(self) -> None:
        css = await request(self.app, "GET", "/static/css/site.css")
        self.assertEqual((css.status, css.headers["content-type"]), (200, "text/css; charset=utf-8"))
        self.assertEqual(css.text, "body { color: red }")
        png = await request(self.app, "GET", "/static/logo.png")
        self.assertEqual((png.headers["content-type"], png.body), ("image/png", b"\x89PNG"))

    async def test_stays_inside_the_folder(self) -> None:
        for path in ("/static/../static_private/secret.txt", "/static/css/../../static_private/secret.txt"):
            self.assertEqual((await request(self.app, "GET", path)).status, 404, path)
        # Even with a route that captures anything, the resolved path is checked.
        for path in ("/raw/../static_private/secret.txt", "/raw//etc/passwd", "/raw/css"):
            self.assertEqual((await request(self.app, "GET", path)).status, 404, path)

    def test_filepath_pattern(self) -> None:
        self.assertEqual(check_and_extract("/f/a/b-c_d.e f.txt", "/f/{filepath}"), ("a/b-c_d.e f.txt",))
        self.assertEqual(check_and_extract("/f/..data", "/f/{filepath}"), ("..data",))
        for bad in ("/f/../x", "/f/a/../x", "/f/a/..", "/f//etc"):
            self.assertIsNone(check_and_extract(bad, "/f/{filepath}"), bad)


class RPCTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.app = reugin.Reugin()
        api = self.app.connect(RPCConnector("api"))

        @api.rpc()
        async def add(call: RemoteCall, a: int, b: int) -> int:
            return a + b

        @api.rpc("whoami")
        async def who(call: RemoteCall) -> dict[str, str | None]:
            return {"agent": call.headers.get("user-agent")}

        @api.rpc()
        async def broken(call: RemoteCall) -> None:
            raise RuntimeError("nope")

        logging.disable(logging.CRITICAL)

    def tearDown(self) -> None:
        logging.disable(logging.NOTSET)

    async def call(self, name: str, args: str | None = None) -> tuple[int, object]:
        r = await request(self.app, "GET", f"/_reuginpowered_/rpc/api/{name}", query=f"args={args}" if args else "")
        return r.status, r.json()

    async def test_calls(self) -> None:
        self.assertEqual(await self.call("add", "[2,3]"), (200, 5))
        self.assertEqual(await self.call("add", "%5B2%2C3%5D"), (200, 5))
        r = await request(self.app, "GET", "/_reuginpowered_/rpc/api/whoami", headers=[("User-Agent", "tests")])
        self.assertEqual(r.json(), {"agent": "tests"})

    async def test_errors(self) -> None:
        self.assertEqual(await self.call("nope"), (404, {"status": "err", "reason": "rpc not found"}))
        self.assertEqual((await self.call("add", "[1]"))[0], 400)
        self.assertEqual((await self.call("add", "[1,"))[0], 400)
        self.assertEqual((await self.call("add", '{"a":1}'))[0], 400)
        self.assertEqual(await self.call("broken"), (500, {"status": "err", "reason": "internal server error"}))

    def test_duplicate_name(self) -> None:
        api = RPCConnector("x")

        @api.rpc("same")
        async def one(call: RemoteCall) -> None: ...

        with self.assertRaises(ValueError):

            @api.rpc("same")
            async def two(call: RemoteCall) -> None: ...


if __name__ == "__main__":
    unittest.main()
