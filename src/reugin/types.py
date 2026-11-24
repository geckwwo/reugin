"""Type aliases shared across Reugin. This module imports nothing from the package."""

from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

type Scope = MutableMapping[str, Any]
"""The ASGI connection scope."""
type Message = MutableMapping[str, Any]
"""An ASGI event, received or sent."""
type Receive = Callable[[], Awaitable[Message]]
type Send = Callable[[Message], Awaitable[None]]
type ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

type JSON = str | int | float | bool | list[JSON] | dict[str, JSON] | None
type Headers = dict[str, str]

type LifespanHandler = Callable[[], Awaitable[None]]
