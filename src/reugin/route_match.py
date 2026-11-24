import re
from collections.abc import Mapping
from functools import lru_cache

from .methods import Methods

MATCHING_TYPES = {
    "alphanumeric": r"\w+",
    "path": r"[\w/]+",
    "any": r".+",
    # A relative path: no leading slash and no ".." segment. StaticContent checks the resolved path as well.
    "filepath": r"(?!/)(?!(?:.*/)?\.\.(?:/|$))[\w .\-/]+",
}


@lru_cache(maxsize=1024)
def compile_route(pattern: str) -> re.Pattern[str]:
    """Turn a route such as `/user/{alphanumeric}` into a regex with one group per placeholder."""
    regex = re.escape(pattern)
    for type_name, type_regex in MATCHING_TYPES.items():
        regex = regex.replace(re.escape(f"{{{type_name}}}"), f"({type_regex})")
    regex = regex.replace(re.escape("{}"), f"({MATCHING_TYPES['any']})")
    return re.compile(f"^{regex}$")


def check_and_extract(path: str, pattern: str) -> tuple[str, ...] | None:
    match = compile_route(pattern).match(path)
    return match.groups() if match else None


def match_route[H](path: str, routes: Mapping[str, H]) -> tuple[H, tuple[str, ...]] | tuple[None, None]:
    for pattern, handler in routes.items():
        if (groups := check_and_extract(path, pattern)) is not None:
            return handler, groups
    return None, None


def match_route_with_method[H](
    path: str, method: Methods, routes: Mapping[tuple[str, Methods], H]
) -> tuple[H, tuple[str, ...]] | tuple[None, None]:
    for (pattern, route_method), handler in routes.items():
        if route_method == method and (groups := check_and_extract(path, pattern)) is not None:
            return handler, groups
    return None, None
