"""Route patterns and the table that matches requests to them.

A pattern is a path with named placeholders: `/notes/{id:int}`, `/hello/{name}`, `/files/{rest:path}`.
"""

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

PLACEHOLDER = re.compile(r"\{([A-Za-z_]\w*)(?::(\w+))?\}")
STATIC_RANK = 10.0


def _segment(value: str) -> str:
    if value in (".", ".."):
        raise ValueError(value)
    return value


def _relative_path(value: str) -> str:
    if value.startswith("/") or "\x00" in value or any(part in (".", "..") for part in value.split("/")):
        raise ValueError(value)
    return value


@dataclass(frozen=True)
class Converter:
    regex: str
    convert: Callable[[str], object]
    """Raises ValueError when the text doesn't fit, and the route doesn't match."""
    rank: float
    """How specific the placeholder is: when two routes match a path, the higher rank wins."""


CONVERTERS: dict[str, Converter] = {
    "str": Converter(r"[^/]+", _segment, 2),
    "int": Converter(r"[0-9]+", int, 3),
    "path": Converter(r".+", _relative_path, 1),
}
"""`str` is one path segment, `int` digits, `path` one or more segments without `..`."""


def _segment_rank(segment: str) -> float:
    kinds = [kind or "str" for _, kind in PLACEHOLDER.findall(segment)]
    if not kinds:
        return STATIC_RANK
    rank = min(CONVERTERS[kind].rank for kind in kinds)
    return rank + 0.5 if PLACEHOLDER.sub("", segment) else rank  # "page-{n:int}" beats "{name}"


@dataclass
class Route[H, W]:
    pattern: str
    regex: re.Pattern[str]
    converters: dict[str, Callable[[str], object]]
    rank: tuple[float, ...]
    http: dict[str, H] = field(default_factory=dict[str, H])
    websocket: W | None = None

    @classmethod
    def compile(cls, pattern: str) -> "Route[H, W]":
        if not pattern.startswith("/"):
            raise ValueError(f"route {pattern!r} must start with /")
        regex: list[str] = []
        converters: dict[str, Callable[[str], object]] = {}
        end = 0
        for match in PLACEHOLDER.finditer(pattern):
            name, kind = match[1], match[2] or "str"
            if kind not in CONVERTERS:
                raise ValueError(f"route {pattern!r}: unknown type {kind!r}, expected one of {', '.join(CONVERTERS)}")
            if name in converters:
                raise ValueError(f"route {pattern!r} uses {{{name}}} twice")
            regex += [re.escape(pattern[end : match.start()]), f"(?P<{name}>{CONVERTERS[kind].regex})"]
            converters[name] = CONVERTERS[kind].convert
            end = match.end()
        regex.append(re.escape(pattern[end:]))
        leftover = PLACEHOLDER.sub("", pattern)
        if "{" in leftover or "}" in leftover:
            raise ValueError(f"route {pattern!r}: placeholders need a name, such as {{name}} or {{id:int}}")
        rank = tuple(_segment_rank(segment) for segment in pattern.split("/")[1:])
        return cls(pattern, re.compile("".join(regex)), converters, rank)

    @property
    def params(self) -> list[str]:
        return list(self.converters)

    def match(self, path: str) -> dict[str, object] | None:
        found = self.regex.fullmatch(path)
        if found is None:
            return None
        try:
            return {name: convert(found[name]) for name, convert in self.converters.items()}
        except ValueError:
            return None


@dataclass
class HTTPMatch[H]:
    handler: H | None
    params: dict[str, object]
    allowed: set[str]
    """When no handler fits the method: the methods that this path does have. Empty means 404."""


class Router[H, W]:
    """One table for HTTP and WebSocket routes. More specific routes are tried first: fixed segments,
    then `int`, then `str`, then `path` placeholders; routes that tie keep the order they were added in.
    """

    def __init__(self) -> None:
        self.routes: list[Route[H, W]] = []

    def route(self, pattern: str) -> Route[H, W]:
        for route in self.routes:
            if route.pattern == pattern:
                return route
        route = Route[H, W].compile(pattern)
        self.routes.append(route)
        self.routes.sort(key=lambda r: tuple(-rank for rank in r.rank))  # stable, so ties keep their order
        return route

    def add_http(self, pattern: str, methods: Iterable[str], handler: H) -> Route[H, W]:
        route = self.route(pattern)
        for method in methods:
            method = method.upper()
            if method in route.http:
                raise ValueError(f"{method} {pattern} already has a handler")
            route.http[method] = handler
        return route

    def add_websocket(self, pattern: str, handler: W) -> Route[H, W]:
        route = self.route(pattern)
        if route.websocket is not None:
            raise ValueError(f"WebSocket {pattern} already has a handler")
        route.websocket = handler
        return route

    def match_http(self, path: str, method: str) -> HTTPMatch[H]:
        allowed: set[str] = set()
        for route in self.routes:
            if not route.http or (params := route.match(path)) is None:
                continue
            handler = route.http.get(method)
            if handler is None and method == "HEAD":
                handler = route.http.get("GET")
            if handler is not None:
                return HTTPMatch(handler, params, set())
            allowed.update(route.http)
        if "GET" in allowed:
            allowed.add("HEAD")
        return HTTPMatch(None, {}, allowed)

    def match_websocket(self, path: str) -> tuple[W, dict[str, object]] | None:
        for route in self.routes:
            if route.websocket is not None and (params := route.match(path)) is not None:
                return route.websocket, params
        return None
