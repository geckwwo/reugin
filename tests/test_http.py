import logging
import unittest

import reugin
import reugin.rhtml as h
from reugin import HTMLResponse, HTTPError, JSONResponse, Request, Response
from reugin.connectors import HTTPConnector

from .asgi import request


def make_app() -> reugin.Reugin:
    app = reugin.Reugin()
    http = app.connect(HTTPConnector())

    @http.get("/")
    async def index(req: Request) -> h.Tag:
        return h.p("Hello, world!")

    @http.get("/hello/{alphanumeric}")
    async def hello(req: Request, name: str) -> dict[str, str]:
        return {"hello": name}

    @http.get("/list")
    async def as_list(req: Request) -> list[int]:
        return [1, 2, 3]

    @http.get("/html")
    async def as_str(req: Request) -> str:
        return "<b>raw</b>"

    @http.get("/files/{path}/{}")
    async def two_captures(req: Request, folder: str, rest: str) -> dict[str, str]:
        return {"folder": folder, "rest": rest}

    @http.post("/notes", [reugin.Methods.PUT])
    async def add_note(req: Request) -> Response:
        note = req.get_body_json()
        assert isinstance(note, dict)
        return JSONResponse(201, {"saved": note["text"], "method": req.method}, {"X-Note": "1"})

    @http.post("/form")
    async def form(req: Request) -> dict[str, str]:
        return req.get_body_form()

    @http.post("/upload")
    async def upload(req: Request) -> dict[str, str | None]:
        return {f.name: f.filename or f.text for f in req.get_body_multipart_formdata()}

    @http.get("/query")
    async def query(req: Request) -> dict[str, str]:
        return req.params

    @http.get("/teapot")
    async def teapot(req: Request) -> Response:
        raise HTTPError(418)

    @http.get("/boom")
    async def boom(req: Request) -> Response:
        raise RuntimeError("boom")

    @http.get("/bytes")
    async def as_bytes(req: Request) -> Response:
        return Response(200, "image/png", b"\x89PNG")

    @http.get("/none")
    async def nothing(req: Request) -> None:
        return None

    @http.route("/both", ["get", "post"])
    async def both(req: Request) -> Response:
        return HTMLResponse(200, req.method)

    return app


class HTTPTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.app = make_app()
        logging.disable(logging.CRITICAL)

    def tearDown(self) -> None:
        logging.disable(logging.NOTSET)

    async def test_tag_is_html(self) -> None:
        r = await request(self.app, "GET", "/")
        self.assertEqual(r.status, 200)
        self.assertEqual(r.headers["content-type"], "text/html; charset=utf-8")
        self.assertEqual(r.text, "<p>Hello, world!</p>")
        self.assertEqual(r.headers["content-length"], str(len(r.body)))

    async def test_captures_and_json(self) -> None:
        r = await request(self.app, "GET", "/hello/gecko")
        self.assertEqual((r.status, r.headers["content-type"], r.json()), (200, "application/json", {"hello": "gecko"}))
        self.assertEqual(
            (await request(self.app, "GET", "/files/a/b/c.txt")).json(), {"folder": "a/b", "rest": "c.txt"}
        )

    async def test_list_and_str(self) -> None:
        self.assertEqual((await request(self.app, "GET", "/list")).json(), [1, 2, 3])
        self.assertEqual((await request(self.app, "GET", "/html")).text, "<b>raw</b>")

    async def test_response_with_status_and_headers(self) -> None:
        for method in ("POST", "PUT"):
            r = await request(
                self.app, method, "/notes", body=b'{"text": "hi"}', headers=[("Content-Type", "application/json")]
            )
            self.assertEqual(r.status, 201)
            self.assertEqual(r.json(), {"saved": "hi", "method": method})
            self.assertEqual(r.headers["x-note"], "1")

    async def test_body_in_chunks(self) -> None:
        r = await request(
            self.app,
            "POST",
            "/notes",
            body=b'{"text": "chunked"}',
            headers=[("content-type", "application/json")],
            chunk=4,
        )
        self.assertEqual(r.json(), {"saved": "chunked", "method": "POST"})

    async def test_body_limit(self) -> None:
        self.app.max_request_body = 10
        r = await request(self.app, "POST", "/notes", body=b"x" * 11, headers=[("content-type", "application/json")])
        self.assertEqual(r.status, 413)

    async def test_json_errors(self) -> None:
        self.assertEqual((await request(self.app, "POST", "/notes", body=b"{}")).status, 415)
        r = await request(self.app, "POST", "/notes", body=b"{nope", headers=[("content-type", "application/json")])
        self.assertEqual(r.status, 400)

    async def test_urlencoded_form(self) -> None:
        r = await request(
            self.app,
            "POST",
            "/form",
            body=b"name=Gecko+Nerd&note=a%26b",
            headers=[("content-type", "application/x-www-form-urlencoded")],
        )
        self.assertEqual(r.json(), {"name": "Gecko Nerd", "note": "a&b"})

    async def test_multipart(self) -> None:
        body = (
            b"--XyZ\r\n"
            b'Content-Disposition: form-data; name="title"\r\n\r\n'
            b"Hello\r\n"
            b"--XyZ\r\n"
            b'Content-Disposition: form-data; name="file"; filename="a b.txt"\r\n'
            b"Content-Type: text/plain\r\n\r\n"
            b"line one\r\nline two\r\n"
            b"--XyZ--\r\n"
        )
        r = await request(
            self.app, "POST", "/upload", body=body, headers=[("content-type", 'multipart/form-data; boundary="XyZ"')]
        )
        self.assertEqual(r.json(), {"title": "Hello", "file": "a b.txt"})
        bad = await request(
            self.app, "POST", "/upload", body=b"nope", headers=[("content-type", "multipart/form-data")]
        )
        self.assertEqual(bad.status, 400)

    async def test_query_is_decoded(self) -> None:
        r = await request(self.app, "GET", "/query", query="q=caf%C3%A9+au+lait&flag&x=1%3D2")
        self.assertEqual(r.json(), {"q": "café au lait", "flag": "", "x": "1=2"})

    async def test_errors(self) -> None:
        self.assertEqual((await request(self.app, "GET", "/missing")).status, 404)
        self.assertEqual((await request(self.app, "DELETE", "/")).status, 404)
        self.assertEqual((await request(self.app, "PROPFIND", "/")).status, 404)
        teapot = await request(self.app, "GET", "/teapot")
        self.assertEqual(teapot.status, 418)
        self.assertIn("418 I&#x27;m a Teapot", teapot.text)
        self.assertEqual((await request(self.app, "GET", "/boom")).status, 500)
        self.assertEqual((await request(self.app, "GET", "/none")).status, 500)

    async def test_bytes_and_methods(self) -> None:
        r = await request(self.app, "GET", "/bytes")
        self.assertEqual((r.headers["content-type"], r.body), ("image/png", b"\x89PNG"))
        self.assertEqual((await request(self.app, "POST", "/both")).text, "POST")

    async def test_error_hook_and_priority(self) -> None:
        app = make_app()
        seen: list[str] = []

        @app.errorhook(priority=10)
        async def hook(scope: object, receive: object, send: object, app_: object, exc: Exception) -> bool:
            seen.append(str(exc))
            return False  # let the default 500 page answer

        self.assertEqual((await request(app, "GET", "/boom")).status, 500)
        self.assertEqual(seen, ["boom"])

    async def test_without_defaults(self) -> None:
        app = reugin.Reugin(no_defaults=True)
        with self.assertRaises(NotImplementedError):
            await request(app, "GET", "/")


if __name__ == "__main__":
    unittest.main()
