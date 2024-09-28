from .base import BaseConnector
from ..response import JSONResponse
import json
import urllib
import logging

class RemoteCall:
    def __init__(self):
        self.path = None
        self.body = None
        self.method = None
        self.params = None
        self.headers = None
        self.addr = None
        self._asgi_scope = None

class RPCConnector(BaseConnector):
    def __init__(self, rpc_scope):
        self.rpc_scope = rpc_scope
        self.rpcs = {}
    
    def rpc(self, rpc_name=None):
        def inner(fn):
            nonlocal rpc_name
            if rpc_name is None:
                rpc_name = fn.__code__.co_name
            assert rpc_name not in self.rpcs, "RPC Call with this name exists already"
            self.rpcs[rpc_name] = fn
            return fn
        return inner
    
    async def process_scope(self, scope, receive, send, reugin):
        if scope['type'] != 'http':
            return False

        try:
            req = RemoteCall()
            req.path = scope['path']
            req.method = scope['method']
            req.params = dict(qc.split("=") for qc in scope['query_string'].decode().split("&")) if len(scope['query_string'].decode().strip()) > 0 else {}
            req.headers = dict(map(lambda x: (y.decode() for y in x), scope['headers']))
            req.addr = scope['client']
            req._asgi_scope = scope

            if not req.path.startswith(f"/_reuginpowered_/rpc/{self.rpc_scope}/"):
                return False
            
            for rpc_name, rpc in self.rpcs.items():
                if req.path == f"/_reuginpowered_/rpc/{self.rpc_scope}/{rpc_name}":
                    body = b''
                    while True:
                        recvscope = await receive()
                        assert recvscope['type'] == 'http.request'

                        body += recvscope['body']
                        if recvscope['more_body'] == False:
                            break
                        assert len(body) >= reugin.max_request_body and reugin.max_request_body >= 0, "Max body length exceeded"
                    req.body = body.decode()
                    try:
                        await JSONResponse(200, json.dumps(await rpc(req, *json.loads(urllib.parse.unquote(req.params.get("args", '%5B%5D')))))).send(send)
                    except TypeError:
                        await JSONResponse(400, {"status": "err", "reason": "wrong types"}).send(send)
                    except json.JSONDecodeError:
                        await JSONResponse(400, {"status": "err", "reason": "wrong json"}).send(send)
                    except Exception as e:
                        logging.exception(e)
                        await JSONResponse(500, {"status": "err", "reason": "internal server error"}).send(send)
                    return True

            # await JSONResponse(404, {"status": "err", "reason": "rpc not found"}).send(send)
            return False # don't send 404 - this will be handled by root server (or further connectors)
        except Exception as e:
            raise RuntimeError(e) # don't send 500 - this will be handled by root server (or errorhooks)