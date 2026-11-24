from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from typing import TYPE_CHECKING, Any, override

from ..methods import Methods
from ..request import Request
from ..response import HTMLResponse, JSONResponse, Response
from ..rhtml import Tag
from ..route_match import match_route_with_method
from .base import BaseConnector, read_body

if TYPE_CHECKING:
    from ..server import Reugin
    from ..types import JSON, Receive, Scope, Send

type RouteResult = Response | Tag | str | JSON
type RouteHandler = Callable[..., Awaitable[Any]]
"""`async def handler(req: Request, *captures: str) -> RouteResult`"""
type MethodNames = Iterable[Methods | str]


def to_response(result: object) -> Response:
    """Turn what a route returned into a Response: a tag or a string is HTML, a dict or a list is JSON."""
    match result:
        case Response():
            return result
        case Tag():
            return HTMLResponse(200, result.render())
        case str():
            return HTMLResponse(200, result)
        case dict() | list():
            data: JSON = result  # pyright: ignore[reportUnknownVariableType]
            return JSONResponse(200, data)
        case _:
            raise TypeError(f"a route returned {type(result).__name__}; expected a Response, a tag, str, dict or list")


class HTTPConnector(BaseConnector):
    def __init__(self) -> None:
        self.routes: dict[tuple[str, Methods], RouteHandler] = {}

    def route[H: RouteHandler](self, route: str, methods: MethodNames | None = None) -> Callable[[H], H]:
        """Register a handler for `route` and the given methods (GET by default)."""

        def register(fn: H) -> H:
            for method in methods or [Methods.GET]:
                self.routes[route, Methods(method.upper())] = fn
            return fn

        return register

    def get[H: RouteHandler](self, route: str, other_methods: MethodNames | None = None) -> Callable[[H], H]:
        return self.route(route, [Methods.GET, *(other_methods or [])])

    def post[H: RouteHandler](self, route: str, other_methods: MethodNames | None = None) -> Callable[[H], H]:
        return self.route(route, [Methods.POST, *(other_methods or [])])

    def head[H: RouteHandler](self, route: str, other_methods: MethodNames | None = None) -> Callable[[H], H]:
        return self.route(route, [Methods.HEAD, *(other_methods or [])])

    def options[H: RouteHandler](self, route: str, other_methods: MethodNames | None = None) -> Callable[[H], H]:
        return self.route(route, [Methods.OPTIONS, *(other_methods or [])])

    def trace[H: RouteHandler](self, route: str, other_methods: MethodNames | None = None) -> Callable[[H], H]:
        return self.route(route, [Methods.TRACE, *(other_methods or [])])

    def put[H: RouteHandler](self, route: str, other_methods: MethodNames | None = None) -> Callable[[H], H]:
        return self.route(route, [Methods.PUT, *(other_methods or [])])

    def delete[H: RouteHandler](self, route: str, other_methods: MethodNames | None = None) -> Callable[[H], H]:
        return self.route(route, [Methods.DELETE, *(other_methods or [])])

    def patch[H: RouteHandler](self, route: str, other_methods: MethodNames | None = None) -> Callable[[H], H]:
        return self.route(route, [Methods.PATCH, *(other_methods or [])])

    @override
    async def process_scope(self, scope: Scope, receive: Receive, send: Send, reugin: Reugin) -> bool:
        if scope["type"] != "http":
            return False
        try:
            method = Methods(scope["method"].upper())
        except ValueError:
            return False  # a method Reugin doesn't route, such as PROPFIND

        handler, captures = match_route_with_method(scope["path"], method, self.routes)
        if handler is None or captures is None:
            return False  # the next connector (or the 404 page) answers

        body = await read_body(receive, reugin.max_request_body)
        result = await handler(Request(scope, body), *captures)
        await to_response(result).send(send)
        return True
