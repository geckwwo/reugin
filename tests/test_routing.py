import unittest

from reugin import Request, Reugin
from reugin.routing import Route, Router
from reugin.testing import TestClient
from reugin.types import Receive, Scope, Send


class PatternTest(unittest.TestCase):
    def test_typed_placeholders(self) -> None:
        route = Route[None, None].compile("/notes/{id:int}/{slug}")
        self.assertEqual(route.match("/notes/12/hello"), {"id": 12, "slug": "hello"})
        self.assertIsNone(route.match("/notes/x/hello"))
        self.assertIsNone(route.match("/notes/12/a/b"))

    def test_path_placeholder_rejects_dot_segments(self) -> None:
        route = Route[None, None].compile("/files/{rest:path}")
        self.assertEqual(route.match("/files/a/b.txt"), {"rest": "a/b.txt"})
        for bad in ("/files/../x", "/files/a/../../x", "/files/..", "/files//etc", "/files/a\x00"):
            self.assertIsNone(route.match(bad), bad)

    def test_str_placeholder_rejects_dot_segments(self) -> None:
        route = Route[None, None].compile("/hello/{name}")
        self.assertIsNone(route.match("/hello/.."))
        self.assertEqual(route.match("/hello/..."), {"name": "..."})

    def test_bad_patterns(self) -> None:
        for pattern in ("notes", "/notes/{}", "/notes/{alphanumeric", "/notes/{id:float}", "/a/{x}/{x}"):
            with self.subTest(pattern), self.assertRaises(ValueError):
                Route[None, None].compile(pattern)

    def test_specific_routes_first(self) -> None:
        router: Router[str, None] = Router()
        router.add_http("/{rest:path}", ["GET"], "rest")
        router.add_http("/notes/{name}", ["GET"], "name")
        router.add_http("/notes/{id:int}", ["GET"], "id")
        router.add_http("/notes/page-{n:int}", ["GET"], "page")
        router.add_http("/notes/new", ["GET"], "new")
        cases = {
            "/notes/new": "new",
            "/notes/12": "id",
            "/notes/page-2": "page",
            "/notes/hello": "name",
            "/other/thing": "rest",
        }
        for path, expected in cases.items():
            self.assertEqual(router.match_http(path, "GET").handler, expected, path)

    def test_one_handler_per_method(self) -> None:
        router: Router[str, None] = Router()
        router.add_http("/a", ["GET"], "first")
        router.add_http("/a", ["POST"], "second")
        with self.assertRaises(ValueError):
            router.add_http("/a", ["get"], "third")


def make_app() -> Reugin:
    app = Reugin()

    @app.get("/notes/{id:int}")
    async def note(req: Request, id: int) -> dict[str, str | int]:
        return {"id": id, "type": type(id).__name__}

    @app.route("/items", ["GET", "POST"])
    async def items(req: Request) -> dict[str, str]:
        return {"method": req.method}

    @app.delete("/items/{name}")
    async def delete_item(req: Request, name: str) -> dict[str, str]:
        return {"deleted": name}

    sub = Reugin()

    @sub.get("/hello")
    async def hello(req: Request) -> dict[str, str]:
        return {"root": req.scope["root_path"], "path": req.path}

    async def raw_app(scope: Scope, receive: Receive, send: Send) -> None:
        body = f"{scope['root_path']} {scope['path']}".encode()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": body})

    app.mount("/sub", sub)
    app.mount("/raw", raw_app)
    return app


class AppRoutingTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.client = TestClient(make_app())

    async def test_placeholders_arrive_by_name_and_converted(self) -> None:
        res = await self.client.get("/notes/12")
        self.assertEqual(res.json(), {"id": 12, "type": "int"})
        res = await self.client.delete("/items/lamp")
        self.assertEqual(res.json(), {"deleted": "lamp"})

    async def test_wrong_placeholder_type_is_404(self) -> None:
        self.assertEqual((await self.client.get("/notes/twelve")).status, 404)

    async def test_wrong_method_is_405_with_allow(self) -> None:
        res = await self.client.put("/items")
        self.assertEqual(res.status, 405)
        self.assertEqual(res.header("allow"), "GET, HEAD, POST")
        self.assertEqual((await self.client.post("/items")).json(), {"method": "POST"})

    async def test_head_uses_the_get_handler(self) -> None:
        get = await self.client.get("/notes/3")
        head = await self.client.request("HEAD", "/notes/3")
        self.assertEqual(head.status, 200)
        self.assertEqual(head.body, b"")
        self.assertEqual(head.header("content-length"), str(len(get.body)))

    async def test_handler_must_take_its_placeholders(self) -> None:
        app = Reugin()
        with self.assertRaises(TypeError):

            @app.get("/users/{id:int}")
            async def user(req: Request) -> str:  # no `id`
                return ""

    async def test_mounts(self) -> None:
        self.assertEqual((await self.client.get("/sub/hello")).json(), {"root": "/sub", "path": "/sub/hello"})
        self.assertEqual((await self.client.get("/raw")).text, "/raw /raw")
        self.assertEqual((await self.client.get("/raw/a/b")).text, "/raw /raw/a/b")
        self.assertEqual((await self.client.get("/subway")).status, 404)

    async def test_bad_mount_prefix(self) -> None:
        with self.assertRaises(ValueError):
            Reugin().mount("/sub/", Reugin())
