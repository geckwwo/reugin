from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import override

from ._meta import VERSION
from .connectors.base import BaseConnector
from .errors import HTTPError
from .response import error_page
from .types import LifespanHandler, Receive, Scope, Send

logger = logging.getLogger("reugin")

type ErrorHook = Callable[[Scope, Receive, Send, Reugin, Exception], Awaitable[bool]]
"""`async def hook(scope, receive, send, app, exc) -> bool`: return True once the error is answered."""

DEFAULTS_PRIORITY = 20000


class Reugin:
    """An ASGI application: a stack of connectors, tried in priority order (lowest first)."""

    max_request_body: int = 256 * 1024
    """Larger request bodies are refused with 413. Negative means no limit."""

    def __init__(self, no_defaults: bool = False) -> None:
        self.connectors: list[tuple[int, BaseConnector]] = []
        self.errorhooks: list[tuple[int, ErrorHook]] = []
        self.lifespan_handlers_start: list[LifespanHandler] = []
        self.lifespan_handlers_stop: list[LifespanHandler] = []
        if not no_defaults:
            self.apply_defaults()

    def connect[C: BaseConnector](self, connector: C, priority: int = 100) -> C:
        """Add a connector. Connectors with the same priority are tried in the order they were added."""
        self.connectors.append((priority, connector))
        self.connectors.sort(key=lambda pair: pair[0])
        return connector

    def errorhook[H: ErrorHook](self, priority: int = 100) -> Callable[[H], H]:
        """Register a hook for errors raised while handling an event. The first hook to return True wins."""

        def register(fn: H) -> H:
            self.errorhooks.append((priority, fn))
            self.errorhooks.sort(key=lambda pair: pair[0])
            return fn

        return register

    def on_startup[F: LifespanHandler](self, fn: F) -> F:
        self.lifespan_handlers_start.append(fn)
        return fn

    def on_shutdown[F: LifespanHandler](self, fn: F) -> F:
        self.lifespan_handlers_stop.append(fn)
        return fn

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            for _, connector in self.connectors:
                if await connector.process_scope(scope, receive, send, self):
                    return
        except HTTPError as e:
            if scope["type"] != "http":
                raise
            await error_page(e.status, e.detail).send(send)
            return
        except Exception as e:
            for _, hook in self.errorhooks:
                if await hook(scope, receive, send, self, e):
                    return
            raise  # nothing handled it: the ASGI server will
        raise NotImplementedError(f"no connector handled this {scope['type']!r} event, and defaults are off")

    def apply_defaults(self) -> None:
        """Add the lifespan handling, the 404 page, and the 500 page with a logged traceback."""
        self.connect(DefaultsConnector(), priority=DEFAULTS_PRIORITY)
        self.errorhook(200)(on_500)


class DefaultsConnector(BaseConnector):
    """Runs the app's startup and shutdown handlers, answers 404 and turns away unknown WebSocket routes."""

    @override
    async def process_scope(self, scope: Scope, receive: Receive, send: Send, reugin: Reugin) -> bool:
        match scope["type"]:
            case "lifespan":
                await run_lifespan(receive, send, reugin)
            case "http":
                await error_page(404, "Not Found").send(send)
            case "websocket":
                await send({"type": "websocket.close", "code": 1000})  # before accept: the server answers 403
            case _:
                return False
        return True


async def run_lifespan(receive: Receive, send: Send, reugin: Reugin) -> None:
    while True:
        message = await receive()
        if message["type"] == "lifespan.startup":
            logger.info("Reugin %s is starting up", VERSION)
            try:
                for handler in reugin.lifespan_handlers_start:
                    await handler()
            except Exception as e:
                logger.exception("A startup handler failed")
                await send({"type": "lifespan.startup.failed", "message": repr(e)})
                return
            await send({"type": "lifespan.startup.complete"})
        elif message["type"] == "lifespan.shutdown":
            logger.info("Shutting down")
            try:
                for handler in reugin.lifespan_handlers_stop:
                    await handler()
            except Exception as e:
                logger.exception("A shutdown handler failed")
                await send({"type": "lifespan.shutdown.failed", "message": repr(e)})
                return
            await send({"type": "lifespan.shutdown.complete"})
            return


async def on_500(scope: Scope, receive: Receive, send: Send, reugin: Reugin, exc: Exception) -> bool:
    logger.error("Error while handling %s %s", scope["type"], scope.get("path", ""), exc_info=exc)
    if scope["type"] == "http":
        await error_page(500, "Internal Server Error").send(send)
        return True
    # A WebSocket handler's errors arrive after its connection is closed (with 1011); logging is all that's left.
    return scope["type"] == "websocket"
