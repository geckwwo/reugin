from typing import Callable, Any, Awaitable, Dict, TypeVar, List
from .connectors.base import BaseConnector
from .request import Request
from .response import Response

TConn = TypeVar("TConn", bound=BaseConnector)
TEHook = TypeVar("TEHook", bound="ErrorHookType")
class ReuginPlaceholder:
    max_request_body: int = 256 * 1024
    def connect(self, connector: TConn, priority: int = 100) -> TConn:
        ...
    def errorhook(self, priority: int = 100) -> Callable[[TEHook], TEHook]:
        ...
    async def __call__(self, scope: ScopeType, receive: ReceiveType, send: SendType):
        ...

ScopeType = Dict[str, Any]
ReceiveType = Callable[[], Awaitable[ScopeType]]
SendType = Callable[[ScopeType], Awaitable[None]]

ErrorHookType = Callable[[ScopeType, ReceiveType, SendType, ReuginPlaceholder, Exception], Awaitable[bool]]
LifespanHandler = Callable[[], Awaitable[None]]

HeadersType = Dict[str, str]

HttpRouteHandler = Callable[[Request], Awaitable[Response | str]]

JsonType = str | int | float | None | List["JsonType"] | Dict[str, "JsonType"]