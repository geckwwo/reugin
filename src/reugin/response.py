class Response:
    def __init__(self, code, content_type, body, headers=None):
        self.code = code
        self.content_type = content_type
        self.body = body
        self.headers = headers or {}
    async def send(self, sender):
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
            'body': self.body.encode() if not isinstance(self, BinaryResponse) else self.body,
        })

class HTMLResponse(Response):
    def __init__(self, code, body, headers=None):
        self.code = code
        self.content_type = "text/html"
        self.body = body
        self.headers = headers or {}
class JSONResponse(Response):
    def __init__(self, code, body, headers=None):
        self.code = code
        self.content_type = "application/json"
        self.body = body
        self.headers = headers or {}

        if isinstance(self.body, dict):
            import json
            self.body = json.dumps(self.body)
class BinaryResponse(Response):
    def __init__(self, code, content_type, body, headers=None):
        self.code = code
        self.content_type = content_type
        self.body = body
        self.headers = headers or {}