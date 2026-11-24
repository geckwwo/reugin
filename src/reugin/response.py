import html
import json
from collections.abc import Mapping

from ._meta import VERSION
from .types import JSON, Send


class Response:
    """An HTTP response. Handlers can also return a tag, a string (HTML) or a dict or list (JSON)."""

    def __init__(
        self,
        code: int,
        content_type: str,
        body: bytes | str,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.code = code
        self.content_type = content_type
        self.body = body.encode() if isinstance(body, str) else body
        self.headers = dict(headers or {})

    async def send(self, send: Send) -> None:
        headers = [
            (b"content-type", self.content_type.encode("latin-1")),
            (b"content-length", str(len(self.body)).encode()),
            *((name.lower().encode("latin-1"), value.encode("latin-1")) for name, value in self.headers.items()),
        ]
        await send({"type": "http.response.start", "status": self.code, "headers": headers})
        await send({"type": "http.response.body", "body": self.body})


class HTMLResponse(Response):
    def __init__(self, code: int, body: str, headers: Mapping[str, str] | None = None) -> None:
        super().__init__(code, "text/html; charset=utf-8", body, headers)


class JSONResponse(Response):
    def __init__(self, code: int, body: JSON, headers: Mapping[str, str] | None = None) -> None:
        super().__init__(code, "application/json", json.dumps(body, ensure_ascii=False), headers)


class BinaryResponse(Response):
    """Kept for 0.2 code: `Response` itself now takes bytes."""


def error_page(code: int, detail: str) -> HTMLResponse:
    """Reugin's plain error page."""
    title = html.escape(f"{code} {detail}")
    return HTMLResponse(code, f"<center><h1>{title}</h1><hr><small>Reugin {VERSION}</small></center>")
