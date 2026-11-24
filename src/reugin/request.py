from __future__ import annotations

import json
from typing import TYPE_CHECKING
from urllib.parse import parse_qsl, unquote

from .errors import HTTPError
from .multipart import MultipartEntry, MultipartError, parse_header_options, parse_multipart
from .types import JSON, Headers, Receive, Scope

if TYPE_CHECKING:
    from .app import Reugin


def parse_query(query_string: bytes) -> dict[str, str]:
    return dict(parse_qsl(query_string.decode("latin-1"), keep_blank_values=True))


def parse_headers(scope: Scope) -> Headers:
    """Lowercase names. A header sent more than once is joined, as HTTP allows (cookies with `; `)."""
    headers: Headers = {}
    raw: list[tuple[bytes, bytes]] = scope.get("headers", [])
    for raw_name, raw_value in raw:
        name, value = raw_name.decode("latin-1").lower(), raw_value.decode("latin-1")
        if name in headers:
            value = headers[name] + ("; " if name == "cookie" else ", ") + value
        headers[name] = value
    return headers


def parse_cookies(header: str) -> dict[str, str]:
    """`a=1; b=2` to a dict. Values are percent-decoded, matching `Response.set_cookie`."""
    cookies: dict[str, str] = {}
    for pair in header.split(";"):
        name, sep, value = pair.strip().partition("=")
        if not sep or not name:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1]
        cookies.setdefault(name.strip(), unquote(value))
    return cookies


class ClientDisconnected(Exception):
    """The client left before sending the whole request body. There's no one to answer."""


async def read_body(receive: Receive, limit: int) -> bytes:
    """Read a whole HTTP request body, or raise HTTPError(413) once it grows past `limit` bytes."""
    body = bytearray()
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            raise ClientDisconnected
        body += message.get("body", b"")
        if limit >= 0 and len(body) > limit:
            raise HTTPError(413)
        if not message.get("more_body", False):
            break
    return bytes(body)


class Connection:
    """What HTTP requests and WebSocket connections have in common."""

    def __init__(self, scope: Scope, app: Reugin, path_params: dict[str, object] | None = None) -> None:
        self.scope = scope
        self.app = app
        """The Reugin app, for `req.app.state`."""
        self.path: str = scope["path"]
        self.query = parse_query(scope.get("query_string", b""))
        """Query string parameters, URL-decoded."""
        self.headers = parse_headers(scope)
        """Header names are lowercase."""
        self.cookies = parse_cookies(self.headers.get("cookie", ""))
        self.path_params: dict[str, object] = path_params or {}
        """The route's placeholders, converted: `{id:int}` gives an int. Handlers get them as arguments too."""
        client: tuple[str, int] | list[str | int] | None = scope.get("client")
        self.client: tuple[str, int] | None = (str(client[0]), int(client[1])) if client else None


class Request(Connection):
    """An HTTP request, as a route handler gets it. The body is read before the handler runs."""

    def __init__(
        self, scope: Scope, app: Reugin, body: bytes = b"", path_params: dict[str, object] | None = None
    ) -> None:
        super().__init__(scope, app, path_params)
        self.method: str = scope.get("method", "GET").upper()
        self.body = body

    @property
    def content_type(self) -> str:
        """The Content-Type without options, lowercase: `application/json`."""
        return parse_header_options(self.headers.get("content-type", ""))[0]

    def json(self) -> JSON:
        if self.content_type != "application/json":
            raise HTTPError(415, "Expected application/json")
        try:
            data: JSON = json.loads(self.body)
        except ValueError as e:
            raise HTTPError(400, "Invalid JSON") from e
        return data

    def form(self) -> dict[str, str]:
        """Fields of a regular HTML form (application/x-www-form-urlencoded)."""
        if self.content_type != "application/x-www-form-urlencoded":
            raise HTTPError(415, "Expected application/x-www-form-urlencoded")
        return parse_query(self.body)

    def multipart(self) -> list[MultipartEntry]:
        """Fields and files of a form sent with enctype="multipart/form-data"."""
        try:
            return parse_multipart(self.headers, self.body)
        except MultipartError as e:
            raise HTTPError(400 if self.content_type == "multipart/form-data" else 415, str(e)) from e
