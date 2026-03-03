import logging
from .connectors.base import BaseConnector
from typing import Dict, List
from .types import ErrorHookType, ScopeType, SendType, ReuginPlaceholder, ReceiveType, LifespanHandler

RD_VER_TRIPLE = (0, 2, 8)
RD_VER = ".".join(map(str, RD_VER_TRIPLE))
RD_ERR_404 = f"<center><h1>404 Not Found</h1><hr><small>Reugin {RD_VER}</small></center>".encode()
RD_ERR_500 = f"<center><h1>500 Internal Server Error</h1><hr><small>Reugin {RD_VER}</small></center>".encode()

class Reugin(ReuginPlaceholder):
    max_request_body: int = 256 * 1024

    def __init__(self, no_defaults: bool = False):
        self.connectors: Dict[int, List[BaseConnector]] = {}
        self.errorhooks: Dict[int, List[ErrorHookType]] = {}

        self.lifespan_handlers_start: List[LifespanHandler] = []
        self.lifespan_handlers_stop: List[LifespanHandler] = []

        if not no_defaults:
            self.apply_defaults()
    
    def connect(self, connector: BaseConnector, priority: int = 100):
        if priority not in self.connectors:
            self.connectors[priority] = []
        self.connectors[priority].append(connector)
        return connector
    
    def errorhook(self, priority: int = 100):
        def inner(fn: ErrorHookType):
            if priority not in self.errorhooks:
                self.errorhooks[priority] = []
            self.errorhooks[priority].append(fn)
            return fn
        return inner
    
    # ASGI Application
    async def __call__(self, scope: ScopeType, receive: ReceiveType, send: SendType):
        try:
            for _, handlers in sorted(self.connectors.items(), key=lambda pair: pair[0]):
                for handler in handlers:
                    if await handler.process_scope(scope, receive, send, self):
                        return
        except Exception as e:
            for _, errorhooks in sorted(self.errorhooks.items(), key=lambda pair: pair[0]):
                for errorhook in errorhooks:
                    if await errorhook(scope, receive, send, self, e):
                        return
            raise e # did not handle - raise, asgi server will handle this itself
            
        raise NotImplementedError("This route has no implementation - defaults were not applied, so this error is thrown.")

    def apply_defaults(self):
        reugin_self = self
        class DefaultsConnector(BaseConnector):
            async def process_scope(self, scope: ScopeType, receive: ReceiveType, send: SendType, reugin: ReuginPlaceholder):
                if scope['type'] == 'lifespan':
                    while True:
                        message = await receive()

                        if message['type'] == 'lifespan.startup':
                            logging.info(f"Reugin {RD_VER} is starting up!")
                            for handler in reugin_self.lifespan_handlers_start:
                                await handler()
                            await send({'type': 'lifespan.startup.complete'})
                        elif message['type'] == 'lifespan.shutdown':
                            logging.info(f"Shutting down!")
                            for handler in reugin_self.lifespan_handlers_stop:
                                await handler()
                            await send({'type': 'lifespan.shutdown.complete'})
                            return True
                elif scope['type'] == 'http':
                    await send({
                        'type': 'http.response.start',
                        'status': 404,
                        'headers': [
                            [b'Content-Type', b'text/html']
                        ],
                    })
                    await send({
                        'type': 'http.response.body',
                        'body': RD_ERR_404
                    })
                    return True
                return False
        
        self.connect(DefaultsConnector(), priority=20000)

        @self.errorhook(200)
        async def on_500(scope: ScopeType, receive: ReceiveType, send: SendType, reugin: ReuginPlaceholder, exc: Exception): # pyright: ignore[reportUnusedFunction]
            logging.exception(exc)
            await send({
                'type': 'http.response.start',
                'status': 500,
                'headers': [
                    [b'Content-Type', b'text/html']
                ],
            })
            await send({
                'type': 'http.response.body',
                'body': RD_ERR_500
            })
            return True