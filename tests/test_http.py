import os
import tempfile
import unittest
from collections.abc import AsyncIterator
from pathlib import Path

import reugin.rhtml as h
from reugin import (
    HTTPError,
    JSONResponse,
    Request,
    Response,
    Reugin,
    StaticFiles,
    StreamingResponse,
    redirect,
)
from reugin.testing import TestClient


def make_app() -> Reugin:
    app = Reugin(max_request_body=1024)

    @app.get("/")
    async def index(req: Request) -> h.Tag:
        return h.p("Hello, world!")

    @app.get("/str")
    async def as_str(req: Request) -> str:
        return "<b>raw</b>"

    @app.get("/list")
    async def as_list(req: Request) -> list[int]:
        return [1, 2, 3]

    @app.post("/notes")
    async def add_note(req: Request) -> Response:
        note = req.json()
        if not isinstance(note, dict) or not note.get("text"):
            raise HTTPError(400, "A note needs some text")
        return JSONResponse({"saved": note["text"]}, 201, headers={"X-Note": "1"})

    @app.post("/form")
    async def form(req: Request) -> dict[str, str]:
        return req.form()

    @app.post("/upload")
    async def upload(req: Request) -> dict[str, str]:
        return {entry.name: entry.filename or entry.text for entry in req.multipart()}

    @app.get("/query")
    async def query(req: Request) -> dict[str, str]:
        return req.query

    @app.get("/teapot")
    async def teapot(req: Request) -> Response:
        raise HTTPError(418, "Short and stout")

    @app.get("/boom")
    async def boom(req: Request) -> Response:
        raise RuntimeError("boom")

    @app.get("/nothing")
    async def nothing(req: Request) -> None:
        return None

    @app.get("/login")
    async def login(req: Request) -> Response:
        response = redirect("/")
        response.set_cookie("session", "a b;c")
        response.set_cookie("theme", "dark", httponly=False, samesite=None)
        return response

    @app.get("/whoami")
    async def whoami(req: Request) -> dict[str, str | None]:
        return {"session": req.cookies.get("session")}

    @app.get("/logout")
    async def logout(req: Request) -> Response:
        response = Response("bye")
        response.delete_cookie("session")
        return response

    @app.get("/stream")
    async def stream(req: Request) -> Response:
        async def pieces() -> AsyncIterator[str | bytes]:
            yield "a"
            yield b"b"

        return StreamingResponse(pieces(), content_type="text/plain")

    @app.get("/empty")
    async def empty(req: Request) -> Response:
        return Response(status=204)

    @app.get("/bad-header")
    async def bad_header(req: Request) -> Response:
        return Response("x", headers={"x-note": "a\r\nSet-Cookie: admin=1"})

    @app.get("/go")
    async def go(req: Request) -> Response:
        return redirect("/notes/" + req.query["to"])

    return app


UTF8_MULTIPART = (
    b"--XyZ\r\n"
    b'Content-Disposition: form-data; name="\xd1\x84\xd0\xb0\xd0\xb9\xd0\xbb"; '
    b'filename="r\xc3\xa9sum\xc3\xa9;v2.pdf"\r\n'
    b"Content-Type: application/pdf\r\n\r\n"
    b"%PDF\r\n"
    b"--XyZ--\r\n"
)

MULTIPART = (
    b"--XyZ\r\n"
    b'Content-Disposition: form-data; name="title"\r\n\r\n'
    b"Holiday\r\n"
    b"--XyZ\r\n"
    b'Content-Disposition: form-data; name="photo"; filename="beach.png"\r\n'
    b"Content-Type: image/png\r\n\r\n"
    b"\x89PNG\r\n"
    b"--XyZ--\r\n"
)


class HTTPTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.client = TestClient(make_app())

    async def test_results_become_responses(self) -> None:
        res = await self.client.get("/")
        self.assertEqual((res.status, res.text), (200, "<p>Hello, world!</p>"))
        self.assertEqual(res.header("content-type"), "text/html; charset=utf-8")
        self.assertEqual((await self.client.get("/str")).text, "<b>raw</b>")
        res = await self.client.get("/list")
        self.assertEqual((res.json(), res.header("content-type")), ([1, 2, 3], "application/json"))

    async def test_json_body(self) -> None:
        res = await self.client.post("/notes", json={"text": "milk"})
        self.assertEqual((res.status, res.json()), (201, {"saved": "milk"}))
        self.assertEqual(res.header("x-note"), "1")
        res = await self.client.post("/notes", json={"text": ""})
        self.assertEqual(res.status, 400)
        self.assertIn("A note needs some text", res.text)

    async def test_json_body_errors(self) -> None:
        res = await self.client.post("/notes", body="{", headers={"content-type": "application/json"})
        self.assertEqual(res.status, 400)
        self.assertEqual((await self.client.post("/notes", form={"text": "milk"})).status, 415)

    async def test_form_and_multipart(self) -> None:
        res = await self.client.post("/form", form={"name": "Ada Lovelace", "empty": ""})
        self.assertEqual(res.json(), {"name": "Ada Lovelace", "empty": ""})
        headers = {"content-type": "multipart/form-data; boundary=XyZ"}
        res = await self.client.post("/upload", body=MULTIPART, headers=headers)
        self.assertEqual(res.json(), {"title": "Holiday", "photo": "beach.png"})
        self.assertEqual((await self.client.post("/upload", json=[])).status, 415)
        res = await self.client.post("/upload", body=UTF8_MULTIPART, headers=headers)
        self.assertEqual(res.json(), {"файл": "résumé;v2.pdf"})

    async def test_query_is_decoded(self) -> None:
        res = await self.client.get("/query?q=a%20b&flag")
        self.assertEqual(res.json(), {"q": "a b", "flag": ""})

    async def test_body_limit(self) -> None:
        self.assertEqual((await self.client.post("/form", body=b"x" * 2000)).status, 413)
        res = await self.client.post("/form", form={"a": "b" * 500}, chunk_size=64)
        self.assertEqual(res.status, 200)

    async def test_error_pages(self) -> None:
        res = await self.client.get("/teapot")
        self.assertEqual(res.status, 418)
        self.assertIn("<h1>418 I&#x27;m a Teapot</h1>", res.text)
        self.assertIn("Short and stout", res.text)
        self.assertEqual((await self.client.get("/missing")).status, 404)

    async def test_unhandled_errors_are_logged_500s(self) -> None:
        for path in ("/boom", "/nothing"):
            with self.subTest(path), self.assertLogs("reugin", "ERROR"):
                self.assertEqual((await self.client.get(path)).status, 500)

    async def test_cookies(self) -> None:
        res = await self.client.get("/login")
        self.assertEqual((res.status, res.header("location")), (303, "/"))
        cookies = [value for name, value in res.headers if name == "set-cookie"]
        self.assertEqual(
            cookies,
            ["session=a%20b%3Bc; Path=/; HttpOnly; SameSite=Lax", "theme=dark; Path=/"],
        )
        self.assertEqual((await self.client.get("/whoami")).json(), {"session": "a b;c"})
        await self.client.get("/logout")
        self.assertEqual((await self.client.get("/whoami")).json(), {"session": None})

    async def test_cookie_names_are_checked(self) -> None:
        with self.assertRaises(ValueError):
            Response().set_cookie("bad name", "x")

    async def test_streaming(self) -> None:
        res = await self.client.get("/stream")
        self.assertEqual(res.text, "ab")
        self.assertIsNone(res.header("content-length"))

    async def test_header_problems_are_500s(self) -> None:
        with self.assertLogs("reugin", "ERROR"):
            res = await self.client.get("/bad-header")
        self.assertEqual(res.status, 500)
        self.assertIsNone(res.header("x-note"))

    async def test_redirects_are_encoded(self) -> None:
        res = await self.client.get("/go?to=%E6%97%A5%E6%9C%AC%20x%0D%0ASet-Cookie:%20a=b")
        self.assertEqual(res.header("location"), "/notes/%E6%97%A5%E6%9C%AC%20x%0D%0ASet-Cookie:%20a=b")
        self.assertIsNone(res.header("set-cookie"))

    async def test_no_content(self) -> None:
        res = await self.client.get("/empty")
        self.assertEqual((res.status, res.body, res.header("content-length")), (204, b"", None))


class ErrorHandlerTest(unittest.IsolatedAsyncioTestCase):
    async def test_error_handlers(self) -> None:
        app = Reugin()
        causes: list[BaseException | None] = []

        @app.get("/key")
        async def key(req: Request) -> str:
            raise KeyError("lamp")

        @app.get("/boom")
        async def boom(req: Request) -> str:
            raise RuntimeError("boom")

        @app.error(404)
        async def not_found(req: Request, error: HTTPError) -> h.Tag:
            return h.p(f"Nothing at {req.path}")

        @app.error(KeyError)
        async def missing(req: Request, error: KeyError) -> dict[str, str]:
            return {"missing": str(error)}

        @app.error(500)
        async def server_error(req: Request, error: HTTPError) -> str:
            causes.append(error.__cause__)
            return "Something broke"

        client = TestClient(app)
        res = await client.get("/nope")
        self.assertEqual((res.status, res.text), (404, "<p>Nothing at /nope</p>"))
        res = await client.get("/key")
        self.assertEqual((res.status, res.json()), (500, {"missing": "'lamp'"}))
        with self.assertLogs("reugin", "ERROR"):
            res = await client.get("/boom")
        self.assertEqual((res.status, res.text), (500, "Something broke"))
        self.assertIsInstance(causes[0], RuntimeError)

    async def test_a_failing_error_page_falls_back(self) -> None:
        app = Reugin()

        @app.error(404)
        async def broken(req: Request, error: HTTPError) -> str:
            raise RuntimeError("the 404 page is broken")

        with self.assertLogs("reugin", "ERROR"):
            res = await TestClient(app).get("/nope")
        self.assertEqual(res.status, 404)
        self.assertIn("404 Not Found", res.text)

    async def test_405_keeps_allow_with_a_custom_page(self) -> None:
        app = Reugin()

        @app.get("/only-get")
        async def only_get(req: Request) -> str:
            return ""

        @app.error(405)
        async def not_allowed(req: Request, error: HTTPError) -> str:
            return "No"

        res = await TestClient(app).post("/only-get")
        self.assertEqual((res.status, res.text, res.header("allow")), (405, "No", "GET, HEAD"))


class StaticTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        (root / "static" / "css").mkdir(parents=True)
        (root / "static" / "css" / "site.css").write_text("body { color: red }")
        (root / "static_old").mkdir()
        (root / "static_old" / "secret.txt").write_text("secret")
        os.symlink(root / "static_old" / "secret.txt", root / "static" / "link.txt")
        app = Reugin()
        app.static("/static", root / "static")
        self.client = TestClient(app)

    async def test_serves_files(self) -> None:
        res = await self.client.get("/static/css/site.css")
        self.assertEqual((res.status, res.text), (200, "body { color: red }"))
        self.assertEqual(res.header("content-type"), "text/css; charset=utf-8")
        self.assertEqual(res.header("content-length"), "19")
        head = await self.client.request("HEAD", "/static/css/site.css")
        self.assertEqual((head.status, head.body, head.header("content-length")), (200, b"", "19"))

    async def test_stays_inside_the_folder(self) -> None:
        for path in (
            "/static/../static_old/secret.txt",
            "/static/%2e%2e/static_old/secret.txt",
            "/static/link.txt",
            "/static/css",
            "/static/missing.txt",
        ):
            with self.subTest(path):
                self.assertEqual((await self.client.get(path)).status, 404)

    @unittest.skipIf(os.geteuid() == 0, "root can read anything")
    async def test_unreadable_file_is_a_500_page(self) -> None:
        locked = Path(self.tmp.name) / "static" / "locked.txt"
        locked.write_text("secret")
        locked.chmod(0)
        self.addCleanup(locked.chmod, 0o644)
        with self.assertLogs("reugin", "ERROR"):
            res = await self.client.get("/static/locked.txt")
        self.assertEqual(res.status, 500)

    async def test_missing_folder_fails_early(self) -> None:
        with self.assertRaises(ValueError):
            StaticFiles(Path(self.tmp.name) / "nope")
