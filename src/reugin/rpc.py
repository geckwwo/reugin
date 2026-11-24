"""RPC: async Python functions the browser can call. `@app.rpc` registers one; inside a `@jsdef`
function, calling it becomes a `fetch` to the app.

On the wire: POST `<rpc_path>/<name>` with a JSON array of arguments. The answer is
`{"ok": true, "result": ...}` or `{"ok": false, "error": "..."}`, with a matching status code.
"""

from __future__ import annotations

import inspect
import json
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, override

from . import _context
from .errors import HTTPError
from .request import Request
from .response import JSONResponse
from .types import JSON
from .unjustpython import JSObject, check_js_name

if TYPE_CHECKING:
    from .app import Reugin

logger = logging.getLogger("reugin")

RPC_HELPER_JS = (
    "async function __reugin_rpc(url, args) {"
    " const response = await fetch(url, {method: 'POST', headers: {'content-type': 'application/json'},"
    " body: JSON.stringify(args)});"
    " let reply;"
    " try { reply = await response.json(); }"
    " catch { throw new Error(`${response.status} ${response.statusText}`); }"
    " if (!reply.ok) { throw new Error(reply.error); }"
    " return reply.result; }"
)


class RPCHelper(JSObject):
    name = "__reugin_rpc"

    @override
    def js_code(self) -> str:
        return RPC_HELPER_JS


RPC_HELPER = RPCHelper()


def takes_request(signature: inspect.Signature) -> bool:
    """True when the first parameter is annotated as a Request: the function gets the call's request first."""
    params = list(signature.parameters.values())
    if not params:
        return False
    annotation: object = params[0].annotation
    if isinstance(annotation, str):  # from __future__ import annotations
        return annotation.rsplit(".", 1)[-1] == "Request"
    return isinstance(annotation, type) and issubclass(annotation, Request)


class RPCFunction[**P, R](JSObject):
    """An async function registered with `@app.rpc`. Python code can still call it directly."""

    def __init__(self, fn: Callable[P, Awaitable[R]], app: Reugin) -> None:
        self.fn = fn
        self.name = check_js_name(fn.__name__)
        self.app = app
        self.signature = inspect.signature(fn)
        self.takes_request = takes_request(self.signature)

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> Awaitable[R]:
        return self.fn(*args, **kwargs)

    @property
    def url(self) -> str:
        return f"{_context.root_path.get()}{self.app.rpc_path}/{self.name}"

    @override
    def js_code(self) -> str:
        return f"function {self.name}(...args) {{ return __reugin_rpc({json.dumps(self.url)}, args); }}"

    @override
    def js_dependencies(self) -> tuple[JSObject]:
        return (RPC_HELPER,)

    def __repr__(self) -> str:
        return f"RPCFunction({self.name!r})"


def reply(status: int, *, result: JSON = None, error: str | None = None) -> JSONResponse:
    if error is None:
        return JSONResponse({"ok": True, "result": result}, status)
    return JSONResponse({"ok": False, "error": error}, status)


async def call_rpc(req: Request, name: str) -> JSONResponse:
    """The route behind every RPC function: `POST <rpc_path>/{name}`."""
    fn: RPCFunction[..., Any] | None = req.app.rpcs.get(name)
    if fn is None:
        return reply(404, error=f"No RPC function named {name!r}")
    # Requiring JSON also keeps other websites out: browsers won't send it across origins without asking first.
    if req.content_type != "application/json":
        return reply(415, error="Expected application/json")
    try:
        args: object = json.loads(req.body)
    except ValueError:
        return reply(400, error="Invalid JSON")
    if not isinstance(args, list):
        return reply(400, error="The body must be a JSON array of arguments")
    call_args: list[object] = [req, *args] if fn.takes_request else list(args)  # pyright: ignore[reportUnknownArgumentType]
    try:
        fn.signature.bind(*call_args)
    except TypeError as e:
        return reply(400, error=f"Wrong arguments: {e}")
    try:
        return reply(200, result=await fn.fn(*call_args))
    except HTTPError as e:
        return reply(e.status, error=e.detail)
    except Exception:
        logger.exception("RPC function %s failed", name)
        return reply(500, error="Internal Server Error")
