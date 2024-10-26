import logging
from .connectors.base import BaseConnector

RD_VER_TRIPLE = (0, 2, 6)
RD_VER = ".".join(map(str, RD_VER_TRIPLE))
RD_ERR_404 = f"<center><h1>404 Not Found</h1><hr><small>Reugin {RD_VER}</small></center>".encode()
RD_ERR_500 = f"<center><h1>500 Internal Server Error</h1><hr><small>Reugin {RD_VER}</small></center>".encode()

class Reugin:
    max_request_body = 256 * 1024

    def __init__(self):
        self.connectors = {}
        self.errorhooks = {}
    
    def connect(self, connector, priority=100):
        if priority not in self.connectors:
            self.connectors[priority] = []
        self.connectors[priority].append(connector)
        return connector
    
    def errorhook(self, priority=100):
        def inner(fn):
            if priority not in self.errorhooks:
                self.errorhooks[priority] = []
            self.errorhooks[priority].append(fn)
            return fn
        return inner
    
    # ASGI Application
    async def __call__(self, scope, receive, send):
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
        self.lifespan_handlers = []

        class DefaultsConnector(BaseConnector):
            async def process_scope(self_dc, scope, receive, send, reugin):
                if scope['type'] == 'lifespan':
                    while True:
                        message = await receive()
                        map(lambda h: h(message), self.lifespan_handlers)

                        if message['type'] == 'lifespan.startup':
                            logging.info(f"Reugin {RD_VER} is starting up!")
                            await send({'type': 'lifespan.startup.complete'})
                        elif message['type'] == 'lifespan.shutdown':
                            logging.info(f"Shutting down!")
                            await send({'type': 'lifespan.shutdown.complete'})
                            return
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
        
        self.connect(DefaultsConnector(), priority=20000)

        @self.errorhook(200)
        async def on_500(scope, receive, send, reugin, exc):
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