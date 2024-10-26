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
    
    def get(self, route, other_methods=None):
        return self.route(route, [Methods.GET] + (other_methods or []))
    def post(self, route, other_methods=None):
        return self.route(route, [Methods.POST] + (other_methods or []))
    def head(self, route, other_methods=None):
        return self.route(route, [Methods.HEAD] + (other_methods or []))
    def options(self, route, other_methods=None):
        return self.route(route, [Methods.OPTIONS] + (other_methods or []))
    def trace(self, route, other_methods=None):
        return self.route(route, [Methods.TRACE] + (other_methods or []))
    def put(self, route, other_methods=None):
        return self.route(route, [Methods.PUT] + (other_methods or []))
    def delete(self, route, other_methods=None):
        return self.route(route, [Methods.DELETE] + (other_methods or []))
    def patch(self, route, other_methods=None):
        return self.route(route, [Methods.PATCH] + (other_methods or []))
    
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

            if (route := match_route_with_method(req.path, Methods(scope['method'].upper()), self.routes))[0] != None:
                body = b''
                while True:
                    recvscope = await receive()
                    assert recvscope['type'] == 'http.request'

                    body += recvscope['body']
                    # bugfix: body length should be checked with <=
                    assert len(body) <= reugin.max_request_body, "Max body length exceeded" 
                    if recvscope['more_body'] == False:
                        break
                req.body = body # removed .decode() - body may be binary if, for example, form with binary file is submitted
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