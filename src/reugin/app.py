from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Callable, Iterable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from . import _context
from ._meta import VERSION
from .errors import HTTPError
from .request import ClientDisconnected, Request, read_body
from .response import Response, error_page, to_response
from .routing import Router
from .rpc import RPCFunction, call_rpc
from .static import StaticFiles
from .types import ASGIApp, LifespanHandler, Receive, Scope, Send
from .websocket import WebSocket, WebSocketHandler

logger = logging.getLogger("reugin")

type Handler = Callable[..., Awaitable[object]]
"""`async def handler(req: Request, **params) -> Response | Tag | str | dict | list`"""
type ErrorHandler = Callable[[Request, Any], Awaitable[object]]
"""`async def page(req: Request, error: HTTPError) -> ...`, or the exception type it was registered for."""


def route_path(scope: Scope) -> str:
    """The path inside this app: without the root_path it's mounted at, if the server included it."""
    path: str = scope["path"]
    root: str = scope.get("root_path", "")
    if root and (path == root or path.startswith(root + "/")):
        return path[len(root) :] or "/"
    return path


def _check_handler(handler: Callable[..., object], params: Iterable[str], where: str) -> None:
    """Fail at import, not on the first request, when a handler can't take its route's placeholders."""
    try:
        signature = inspect.signature(handler)
    except (TypeError, ValueError):
        return
    try:
        signature.bind(None, **dict.fromkeys(params))
    except TypeError as e:
        name = getattr(handler, "__qualname__", repr(handler))
        raise TypeError(f"{name} can't handle {where}: {e}") from None


class Reugin:
    """An ASGI app: routes, WebSocket routes, RPC functions and error pages in one table.

    `max_request_body`: larger request bodies get a 413 (negative for no limit).
    `rpc_path`: where `@app.rpc` functions are served.
    """

    def __init__(self, *, max_request_body: int = 256 * 1024, rpc_path: str = "/_reugin/rpc") -> None:
        self.max_request_body = max_request_body
        self.rpc_path = rpc_path.rstrip("/")
        self.state = SimpleNamespace()
        """Anything the app keeps between requests, such as a database set up `@app.on_startup`."""
        self.router: Router[Handler, WebSocketHandler] = Router()
        self.mounts: list[tuple[str, ASGIApp]] = []
        self.rpcs: dict[str, RPCFunction[..., Any]] = {}
        self.error_handlers: dict[int | type[Exception], ErrorHandler] = {}
        self.startup_handlers: list[LifespanHandler] = []
        self.shutdown_handlers: list[LifespanHandler] = []

    # Registering

    def route[H: Handler](self, path: str, methods: Iterable[str] = ("GET",)) -> Callable[[H], H]:
        """Handle `methods` at `path`. Placeholders such as `{id:int}` are passed by name."""
        methods = list(methods)

        def register(handler: H) -> H:
            route = self.router.add_http(path, methods, handler)
            _check_handler(handler, route.params, f"{'/'.join(methods)} {path}")
            return handler

        return register

    def get[H: Handler](self, path: str) -> Callable[[H], H]:
        return self.route(path, ["GET"])

    def post[H: Handler](self, path: str) -> Callable[[H], H]:
        return self.route(path, ["POST"])

    def put[H: Handler](self, path: str) -> Callable[[H], H]:
        return self.route(path, ["PUT"])

    def patch[H: Handler](self, path: str) -> Callable[[H], H]:
        return self.route(path, ["PATCH"])

    def delete[H: Handler](self, path: str) -> Callable[[H], H]:
        return self.route(path, ["DELETE"])

    def websocket[W: WebSocketHandler](self, path: str) -> Callable[[W], W]:
        """Handle WebSocket connections to `path`: `async def chat(ws: WebSocket, **params)`."""

        def register(handler: W) -> W:
            route = self.router.add_websocket(path, handler)
            _check_handler(handler, route.params, f"WebSocket {path}")
            return handler

        return register

    def rpc[**P, R](self, fn: Callable[P, Awaitable[R]]) -> RPCFunction[P, R]:
        """Let the browser call `fn`. Inside a `@jsdef` function, `await fn(...)` sends the call."""
        rpc = RPCFunction(fn, self)
        if rpc.name in self.rpcs:
            raise ValueError(f"an RPC function named {rpc.name!r} is already registered")
        if not self.rpcs:
            self.router.add_http(f"{self.rpc_path}/{{name}}", ["POST"], call_rpc)
        self.rpcs[rpc.name] = rpc
        return rpc

    def error[E: ErrorHandler](self, key: int | type[Exception]) -> Callable[[E], E]:
        """The page for an error status (`@app.error(404)`), or for an exception type (`@app.error(KeyError)`).

        It returns what a route does; the status is the error's unless it returns a Response.
        """

        if isinstance(key, type) and issubclass(key, HTTPError):
            raise ValueError("pages for HTTPError go by status: @app.error(404)")

        def register(handler: E) -> E:
            self.error_handlers[key] = handler
            return handler

        return register

    def mount(self, prefix: str, app: ASGIApp) -> None:
        """Hand every request under `prefix` to another ASGI app, with root_path set to the prefix."""
        if not prefix.startswith("/") or prefix.endswith("/"):
            raise ValueError(f"mount prefix {prefix!r} must start with / and not end with one")
        self.mounts.append((prefix, app))

    def static(self, prefix: str, directory: str | Path) -> None:
        """Serve the files in `directory` under `prefix`: `app.static("/static", "static")`."""
        self.get(f"{prefix.rstrip('/')}/{{path:path}}")(StaticFiles(directory))

    def on_startup[F: LifespanHandler](self, fn: F) -> F:
        self.startup_handlers.append(fn)
        return fn

    def on_shutdown[F: LifespanHandler](self, fn: F) -> F:
        self.shutdown_handlers.append(fn)
        return fn

    # Serving

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        match scope["type"]:
            case "http" | "websocket":
                path = route_path(scope)
                for prefix, app in self.mounts:
                    if path == prefix or path.startswith(prefix + "/"):
                        root = scope.get("root_path", "") + prefix
                        rest = path[len(prefix) :]
                        await app({**scope, "root_path": root, "path": root + rest}, receive, send)
                        return
                token = _context.root_path.set(scope.get("root_path", ""))
                try:
                    if scope["type"] == "http":
                        await self._http(scope, path, receive, send)
                    else:
                        await self._websocket(scope, path, receive, send)
                finally:
                    _context.root_path.reset(token)
            case "lifespan":
                await self._lifespan(receive, send)
            case other:
                raise ValueError(f"Reugin doesn't handle {other!r} events")

    async def _http(self, scope: Scope, path: str, receive: Receive, send: Send) -> None:
        request = Request(scope, self)
        head = request.method == "HEAD"
        try:
            match = self.router.match_http(path, request.method)
            if match.handler is None:
                if match.allowed:
                    raise HTTPError(405, headers={"allow": ", ".join(sorted(match.allowed))})
                raise HTTPError(404)
            request.path_params = match.params
            request.body = await read_body(receive, self.max_request_body)
            response = to_response(await match.handler(request, **match.params))
            response.start_message(None)  # header problems become a 500 page, not a broken response
        except ClientDisconnected:
            return
        except Exception as e:
            response = await self._error_response(request, e)
        await response.send(send, head=head, receive=receive)

    async def _error_response(self, request: Request, exc: Exception) -> Response:
        if isinstance(exc, HTTPError):
            error = exc
        else:
            handler = next((self.error_handlers[c] for c in type(exc).__mro__ if c in self.error_handlers), None)
            if handler is not None:
                try:
                    return to_response(await handler(request, exc), 500)
                except Exception:
                    logger.exception("The error page for %s failed", type(exc).__name__)
            else:
                logger.error("Error while handling %s %s", request.method, request.path, exc_info=exc)
            error = HTTPError(500)
            error.__cause__ = exc

        response: Response | None = None
        if (page := self.error_handlers.get(error.status)) is not None:
            try:
                response = to_response(await page(request, error), error.status)
            except Exception:
                logger.exception("The %d page failed", error.status)
        if response is None:
            response = error_page(error.status, error.detail)
        response.headers += [(name.lower(), value) for name, value in error.headers.items()]
        return response

    async def _websocket(self, scope: Scope, path: str, receive: Receive, send: Send) -> None:
        if (await receive())["type"] != "websocket.connect":
            return
        found = self.router.match_websocket(path)
        if found is None:
            await send({"type": "websocket.close", "code": 1000})  # before accepting: the server answers 403
            return
        handler, params = found
        await WebSocket(scope, self, send, params).run(handler, receive)

    async def _lifespan(self, receive: Receive, send: Send) -> None:
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                logger.info("Reugin %s is starting up", VERSION)
                try:
                    for handler in self.startup_handlers:
                        await handler()
                except Exception as e:
                    logger.exception("A startup handler failed")
                    await send({"type": "lifespan.startup.failed", "message": repr(e)})
                    return
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                try:
                    for handler in self.shutdown_handlers:
                        await handler()
                except Exception as e:
                    logger.exception("A shutdown handler failed")
                    await send({"type": "lifespan.shutdown.failed", "message": repr(e)})
                    return
                await send({"type": "lifespan.shutdown.complete"})
                return
