import asyncio
import mimetypes
from collections.abc import Awaitable, Callable
from pathlib import Path

from .errors import HTTPError
from .request import Request
from .response import Response

TEXT_TYPES = ("application/javascript", "application/json", "image/svg+xml")


def StaticContent(dir: str | Path) -> Callable[[Request, str], Awaitable[Response]]:
    """A route handler that serves the files in `dir`. Register it on a route with one capture:

    http.get("/static/{filepath}")(reugin.mounts.StaticContent("static"))
    """
    base = Path(dir).resolve()

    async def route(req: Request, relpath: str) -> Response:
        file = (base / relpath).resolve()
        # The resolved path must stay inside `base`: this also catches "..", symlinks and sibling
        # folders whose names start with the same letters ("static" and "static_old").
        if not file.is_relative_to(base) or not file.is_file():
            raise HTTPError(404)
        content_type = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in TEXT_TYPES:
            content_type += "; charset=utf-8"
        return Response(200, content_type, await asyncio.to_thread(file.read_bytes))

    return route
