from .types import HeadersType, SendType, JsonType

class Response:
    def __init__(self, code: int, content_type: str, body: bytes | str, headers: HeadersType | None = None):
        self.code = code
        self.content_type = content_type
        self.body = body
        self.headers = headers or {}
    async def send(self, sender: SendType):
        await sender({
            'type': 'http.response.start',
            'status': self.code,
            'headers': [
                [b'Content-Type', self.content_type.encode()],
                *[[x.encode(), str(y).encode()] for x, y in self.headers.items()]
            ],
        })
        await sender({
            'type': 'http.response.body',
            'body': self.body.encode() if not isinstance(self, BinaryResponse) else self.body, # type: ignore
        })

class HTMLResponse(Response):
    def __init__(self, code: int, body: str, headers: HeadersType | None = None):
        self.code = code
        self.content_type = "text/html"
        self.body = body
        self.headers = headers or {}

class JSONResponse(Response):
    def __init__(self, code: int, body: JsonType, headers: HeadersType | None = None):
        self.code = code
        self.content_type = "application/json"
        self.body = body
        self.headers = headers or {}

        if isinstance(self.body, dict):
            import json
            self.body = json.dumps(self.body)

class BinaryResponse(Response):
    def __init__(self, code: int, content_type: str, body: bytes, headers: HeadersType | None = None):
        self.code = code
        self.content_type = content_type
        self.body = body
        self.headers = headers or {}