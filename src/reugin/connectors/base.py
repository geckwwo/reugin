from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from ..errors import HTTPError
from ..types import Receive

if TYPE_CHECKING:
    from ..server import Reugin
    from ..types import Scope, Send


class BaseConnector(ABC):
    """Handles some of the ASGI events that reach a Reugin app (see `Reugin.connect`)."""

    @abstractmethod
    async def process_scope(self, scope: Scope, receive: Receive, send: Send, reugin: Reugin) -> bool:
        """Answer the event and return True, or return False to pass it to the next connector."""


async def read_body(receive: Receive, limit: int) -> bytes:
    """Read a whole HTTP request body, or raise HTTPError(413) once it grows past `limit` bytes."""
    body = bytearray()
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            break
        body += message.get("body", b"")
        if limit >= 0 and len(body) > limit:
            raise HTTPError(413)
        if not message.get("more_body", False):
            break
    return bytes(body)
