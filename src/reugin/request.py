from .multipartformdata import parse_multipart_formdata as _pmfd
from .types import HeadersType, ScopeType
from typing import Dict

class Request:
    def __init__(self):
        self.path = "/"
        self.body = b""
        self.method = ""
        self.params: Dict[str, str] = {}
        self.addr = None
        self.headers: HeadersType = {}
        self.asgi_scope: ScopeType = {}
    
    def get_body_json(self):
        assert "content-type" in self.headers, "Request has no Content-Type header"
        assert self.headers["content-type"].split(";")[0].strip().lower() == "application/json", "Content-Type is not JSON"

        import json
        return json.loads(self.body.decode())
    
    def get_body_multipart_formdata(self):
        return _pmfd(self.headers, self.body)