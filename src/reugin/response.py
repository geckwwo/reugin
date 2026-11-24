import asyncio
import json
import mimetypes
import os
import re
from collections.abc import AsyncIterable, AsyncIterator, Iterable, Mapping
from pathlib import Path
from typing import Literal, cast, override
from urllib.parse import quote

from . import rhtml as h
from .errors import status_phrase
from .types import JSON, Message, Receive, Send

type HeaderInput = Mapping[str, str] | Iterable[tuple[str, str]] | None

COOKIE_NAME = re.compile(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+")
TEXT_TYPES = ("application/javascript", "application/json", "image/svg+xml")
FILE_CHUNK = 64 * 1024


def header_pairs(headers: HeaderInput) -> list[tuple[str, str]]:
    """Headers as a list of (name, value) pairs, with lowercase names."""
    if headers is None:
        return []
    if isinstance(headers, Mapping):
        return [(name.lower(), value) for name, value in cast(Mapping[str, str], headers).items()]
    return [(name.lower(), value) for name, value in headers]


def _no_separators(value: str, what: str) -> str:
    if any(char in value for char in ";\r\n"):
        raise ValueError(f"cookie {what} can't contain ';' or line breaks: {value!r}")
    return value


class Response:
    """An HTTP response. Handlers can also return a tag or a string (HTML), or a dict or a list (JSON).

    `headers` is a list of (name, value) pairs, so a name can repeat, as `Set-Cookie` does.
    """

    def __init__(
        self,
        body: bytes | str = b"",
        status: int = 200,
        *,
        content_type: str | None = None,
        headers: HeaderInput = None,
    ) -> None:
        self.status = status
        self.body = body.encode() if isinstance(body, str) else body
        if content_type is None and body:
            content_type = "text/plain; charset=utf-8" if isinstance(body, str) else "application/octet-stream"
        self.content_type = content_type
        self.headers = header_pairs(headers)

    def set_cookie(
        self,
        name: str,
        value: str,
        *,
        max_age: int | None = None,
        path: str = "/",
        domain: str | None = None,
        secure: bool = False,
        httponly: bool = True,
        samesite: Literal["lax", "strict", "none"] | None = "lax",
    ) -> None:
        """Add a Set-Cookie header. The value is percent-encoded; `Request.cookies` decodes it."""
        if not COOKIE_NAME.fullmatch(name):
            raise ValueError(f"not a valid cookie name: {name!r}")
        parts = [f"{name}={quote(value, safe='')}"]
        if max_age is not None:
            parts.append(f"Max-Age={max_age}")
        if path:
            parts.append(f"Path={_no_separators(path, 'path')}")
        if domain:
            parts.append(f"Domain={_no_separators(domain, 'domain')}")
        if secure:
            parts.append("Secure")
        if httponly:
            parts.append("HttpOnly")
        if samesite:
            parts.append(f"SameSite={samesite.capitalize()}")
        self.headers.append(("set-cookie", "; ".join(parts)))

    def delete_cookie(self, name: str, *, path: str = "/", domain: str | None = None) -> None:
        self.set_cookie(name, "", max_age=0, path=path, domain=domain)

    def start_message(self, length: int | None) -> Message:
        """The http.response.start message. Raises ValueError for header values HTTP can't carry."""
        for name, value in self.headers:
            if any(char in name + value for char in "\r\n\0"):
                raise ValueError(f"the {name} header contains a line break or NUL: {value!r}")
        headers: list[tuple[bytes, bytes]] = []
        if self.content_type and not any(name == "content-type" for name, _ in self.headers):
            headers.append((b"content-type", self.content_type.encode("latin-1")))
        # 1xx, 204 and 304 responses carry no body, and no Content-Length either.
        if length is not None and self.status >= 200 and self.status not in (204, 304):
            headers.append((b"content-length", str(length).encode()))
        headers += [(name.encode("latin-1"), value.encode("latin-1")) for name, value in self.headers]
        return {"type": "http.response.start", "status": self.status, "headers": headers}

    async def send(self, send: Send, *, head: bool = False, receive: Receive | None = None) -> None:
        """Send the response. For HEAD requests, `head` keeps the headers and leaves out the body.

        `receive` lets a streaming response notice that the client has left.
        """
        await send(self.start_message(len(self.body)))
        empty = head or self.status in (204, 304)
        await send({"type": "http.response.body", "body": b"" if empty else self.body})


class HTMLResponse(Response):
    def __init__(self, body: str, status: int = 200, *, headers: HeaderInput = None) -> None:
        super().__init__(body, status, content_type="text/html; charset=utf-8", headers=headers)


class JSONResponse(Response):
    def __init__(self, data: JSON, status: int = 200, *, headers: HeaderInput = None) -> None:
        super().__init__(json.dumps(data, ensure_ascii=False), status, content_type="application/json", headers=headers)


class StreamingResponse(Response):
    """A response whose body comes in pieces, from an async iterable such as an async generator."""

    def __init__(
        self,
        chunks: AsyncIterable[bytes | str],
        status: int = 200,
        *,
        content_type: str = "application/octet-stream",
        headers: HeaderInput = None,
        length: int | None = None,
    ) -> None:
        super().__init__(b"", status, content_type=content_type, headers=headers)
        self.chunks = chunks
        self.length = length
        """Sent as Content-Length when known. Otherwise the server picks chunked encoding."""

    @override
    async def send(self, send: Send, *, head: bool = False, receive: Receive | None = None) -> None:
        await send(self.start_message(self.length))
        if head:
            await send({"type": "http.response.body", "body": b""})
            return

        async def stream() -> None:
            async for chunk in self.chunks:
                if chunk:
                    data = chunk.encode() if isinstance(chunk, str) else chunk
                    await send({"type": "http.response.body", "body": data, "more_body": True})
            await send({"type": "http.response.body", "body": b""})

        if receive is None:
            await stream()
            return

        async def client_left() -> None:
            while (await receive())["type"] != "http.disconnect":
                pass

        # Stop when the client leaves, or an endless stream (such as server-sent events) would run forever.
        streaming, watching = asyncio.create_task(stream()), asyncio.create_task(client_left())
        try:
            await asyncio.wait({streaming, watching}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in (streaming, watching):
                task.cancel()
            await asyncio.gather(streaming, watching, return_exceptions=True)
            close = getattr(self.chunks, "aclose", None)
            if close is not None:
                await close()
        if streaming.done() and not streaming.cancelled() and (error := streaming.exception()) is not None:
            raise error


def guess_content_type(path: Path) -> str:
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if content_type.startswith("text/") or content_type in TEXT_TYPES:
        content_type += "; charset=utf-8"
    return content_type


async def _read_file(path: Path) -> AsyncIterator[bytes]:
    file = await asyncio.to_thread(path.open, "rb")
    try:
        while chunk := await asyncio.to_thread(file.read, FILE_CHUNK):
            yield chunk
    finally:
        file.close()


def _readable_size(path: Path) -> int:
    """The file's size, after checking it can be opened, so errors come before any of the response is sent."""
    with path.open("rb") as file:
        return os.fstat(file.fileno()).st_size


class FileResponse(StreamingResponse):
    """A file from disk, read in pieces in a worker thread. The content type is guessed from the name."""

    def __init__(
        self, path: str | Path, status: int = 200, *, content_type: str | None = None, headers: HeaderInput = None
    ) -> None:
        path = Path(path)
        super().__init__(
            _read_file(path),
            status,
            content_type=content_type or guess_content_type(path),
            headers=headers,
            length=_readable_size(path),
        )


def redirect(url: str, status: int = 303) -> Response:
    """Send the browser to `url`. 303 makes it follow with a GET, the usual answer to a form POST.

    Characters a URL can't contain (spaces, line breaks, non-ASCII) are percent-encoded.
    """
    return Response(status=status, headers={"location": quote(url, safe=":/?#[]@!$&'()*+,;=%~")})


def to_response(result: object, status: int = 200) -> Response:
    """Turn what a handler returned into a Response: a tag or a string is HTML, a dict or a list is JSON.

    `status` applies to everything but a Response, which has its own.
    """
    match result:
        case Response():
            return result
        case h.Tag():
            return HTMLResponse(result.render(), status)
        case str():
            return HTMLResponse(result, status)
        case dict() | list():
            data: JSON = result  # pyright: ignore[reportUnknownVariableType]
            return JSONResponse(data, status)
        case _:
            raise TypeError(
                f"a handler returned {type(result).__name__}; expected a Response, a tag, str, dict or list"
            )


ERROR_STYLE = "body{font:16px/1.5 system-ui,sans-serif;max-width:36rem;margin:4rem auto;padding:0 1rem;color:#222}"


def error_page(status: int, detail: str) -> HTMLResponse:
    """Reugin's plain error page, used when the app has no `@app.error` page for the status."""
    heading = f"{status} {status_phrase(status)}"
    page = h.Document(
        h.h1(heading),
        h.p(detail) if detail != status_phrase(status) else None,
        title=heading,
        head=[h.style(ERROR_STYLE)],
    )
    return HTMLResponse(page.render(), status)
