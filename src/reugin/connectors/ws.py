from .base import BaseConnector
import asyncio
from ..route_match import match_route

class WebSocketClosedException(Exception):
    def __init__(self, wsconn, code):
        self.wsconn = wsconn
        self.code = code

class WebSocketConnection:
    def __init__(self):
        self.path = None
        self.params = None
        self.headers = None
        self.addr = None
        
        self._asgi_scope = None
        self._asgi_recv = None
        self._asgi_send = None

        self._conn_broken = False
        self._conn_broken_code = 1005

        self._ws_recv_queue = []

    async def recv(self, read_even_if_closed=False):
        if self._conn_broken and read_even_if_closed:
            raise WebSocketClosedException(self, self._conn_broken_code)
        
        while len(self._ws_recv_queue) == 0:
            if self._conn_broken:
                raise WebSocketClosedException(self, self._conn_broken_code)
            await asyncio.sleep(0)
        return self._ws_recv_queue.pop(0)
    
    async def send(self, data: str | bytes):
        if self._conn_broken:
            raise WebSocketClosedException(self, self._conn_broken_code)
        
        assert isinstance(data, (str, bytes)), "websocket expected string or bytes"
        if isinstance(data, str):
            await self._asgi_send({
                "type": "websocket.send",
                "text": data
            })
        else:
            await self._asgi_send({
                "type": "websocket.send",
                "bytes": data
            })
    
    async def close(self, code=1000, reason=None):
        await self._asgi_send({
            "type": "websocket.close",
            "code": code,
            "reason": reason
        })

    async def is_closed(self):
        return self._conn_broken

class WebSocketConnector(BaseConnector):
    def __init__(self):
        self.wsroutes = {}
    
    def connect(self, ws_route):
        def inner(fn):
            self.wsroutes[ws_route] = fn
            return fn
        return inner

    async def process_scope(self, scope, receive, send, reugin):
        if scope['type'] != 'websocket':
            return False
        
        try:
            req = WebSocketConnection()
            req.path = scope['path']
            req.params = dict(qc.split("=") for qc in scope['query_string'].decode().split("&")) if len(scope['query_string'].decode().strip()) > 0 else {}
            req.headers = dict(map(lambda x: (y.decode() for y in x), scope['headers']))
            req.addr = scope['client']
            req._asgi_scope = scope
            req._asgi_recv = receive
            req._asgi_send = send
            
            if (route := match_route(req.path))[0] != None:
                while True:
                    wsscope = await receive()
                    if wsscope['type'] == "websocket.connect":
                        await send({"type": "websocket.accept"})
                        asyncio.ensure_future(route[0](req))
                    elif wsscope['type'] == "websocket.receive":
                        if "text" in wsscope:
                            data = wsscope['text']
                        else:
                            data = wsscope['bytes']
                        req._ws_recv_queue.append(data)
                    elif wsscope['type'] == "websocket.disconnect":
                        req._conn_broken = True
                        req._conn_broken_code = wsscope['code']
                        break
                    else:
                        raise NotImplementedError(f"ASGI WebSocket event not implemented {wsscope}")
                
                return True # finished
            return False # don't send 404 - this will be handled by root server (or further connectors)
        except Exception as e:
            raise RuntimeError(e) # don't send 500 - this will be handled by root server (or errorhooks)