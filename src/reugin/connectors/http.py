from ..methods import Methods
from ..response import BinaryResponse, Response
from ..request import Request
from ..rhtml import Tag
from ..route_match import match_route_with_method
from .base import BaseConnector
import json


class HTTPConnector(BaseConnector):
    def __init__(self):
        self.routes = {}

    def route(self, route, methods=None):
        def inner(fn):
            for method in methods or [Methods.GET]:
                self.routes[route, method] = fn
            return fn
        return inner
    
    async def process_scope(self, scope, receive, send, reugin):
        if scope['type'] != 'http':
            return False
        
        try:
            req = Request()
            req.path = scope['path']
            req.method = scope['method']
            req.params = dict(qc.split("=") for qc in scope['query_string'].decode().split("&")) if len(scope['query_string'].decode().strip()) > 0 else {}
            req.headers = dict(map(lambda x: (y.decode() for y in x), scope['headers']))
            req.addr = scope['client']
            req._asgi_scope = scope

            if (route := match_route_with_method(req.path, Methods(scope['method'].upper())))[0] != None:
                body = b''
                while True:
                    recvscope = await receive()
                    assert recvscope['type'] == 'http.request'

                    body += recvscope['body']
                    if recvscope['more_body'] == False:
                        break
                    assert len(body) >= reugin.max_request_body and reugin.max_request_body >= 0, "Max body length exceeded"
                req.body = body.decode()
                resp: Response = await route[0](req, *route[1])
                if not isinstance(resp, Response):
                    if isinstance(resp, Tag):
                        resp = Response(200, "text/html", resp.render())
                    elif isinstance(resp, dict):
                        resp = Response(200, "application/json", json.dumps(resp))
                    else:
                        assert False, f"Expected Tag or Response, got {type(resp)}"
                await send({
                    'type': 'http.response.start',
                    'status': resp.code,
                    'headers': [
                        [b'Content-Type', resp.content_type.encode()],
                        *[[x.encode(), str(y).encode()] for x, y in resp.headers.items()]
                    ],
                })
                await send({
                    'type': 'http.response.body',
                    'body': resp.body.encode() if not isinstance(resp, BinaryResponse) else resp.body,
                })
                return True # finished
            else:
                return False # don't send 404 - this will be handled by root server (or further connectors)
        except Exception as e:
            raise RuntimeError(e) # don't send 500 - this will be handled by root server (or errorhooks)