from __future__ import annotations

import inspect
import json
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, override

from ..request import Request
from ..response import JSONResponse
from .base import BaseConnector, read_body

if TYPE_CHECKING:
    from ..server import Reugin
    from ..types import Receive, Scope, Send

logger = logging.getLogger("reugin")

type RPCHandler = Callable[..., Awaitable[Any]]
"""`async def fn(call: RemoteCall, *args: JSON) -> JSON`"""


class RemoteCall(Request):
    """The request behind an RPC call. Same fields as `Request`."""


def error(code: int, reason: str) -> JSONResponse:
    return JSONResponse(code, {"status": "err", "reason": reason})


class RPCConnector(BaseConnector):
    """Exposes async functions at `/_reuginpowered_/rpc/<rpc_scope>/<name>?args=<JSON array>`.

    The function gets the call and the decoded arguments, and its return value is sent back as JSON.
    """

    def __init__(self, rpc_scope: str) -> None:
        self.rpc_scope = rpc_scope
        self.rpcs: dict[str, RPCHandler] = {}

    @property
    def prefix(self) -> str:
        return f"/_reuginpowered_/rpc/{self.rpc_scope}/"

    def rpc[F: RPCHandler](self, rpc_name: str | None = None) -> Callable[[F], F]:
        def register(fn: F) -> F:
            name = rpc_name or fn.__name__
            if name in self.rpcs:
                raise ValueError(f"an RPC named {name!r} is already registered")
            self.rpcs[name] = fn
            return fn

        return register

    @override
    async def process_scope(self, scope: Scope, receive: Receive, send: Send, reugin: Reugin) -> bool:
        if scope["type"] != "http" or not scope["path"].startswith(self.prefix):
            return False

        fn = self.rpcs.get(scope["path"].removeprefix(self.prefix))
        if fn is None:
            await error(404, "rpc not found").send(send)
            return True

        call = RemoteCall(scope, await read_body(receive, reugin.max_request_body))
        try:
            args: object = json.loads(call.params.get("args", "[]"))
        except json.JSONDecodeError:
            await error(400, "wrong json").send(send)
            return True
        if not isinstance(args, list):
            await error(400, "args must be a JSON array").send(send)
            return True

        try:
            inspect.signature(fn).bind(call, *args)
        except TypeError:
            await error(400, "wrong arguments").send(send)
            return True

        try:
            result = JSONResponse(200, await fn(call, *args))
        except Exception:
            logger.exception("RPC %s failed", scope["path"])
            result = error(500, "internal server error")
        await result.send(send)
        return True
