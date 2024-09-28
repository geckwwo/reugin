class Request:
    def __init__(self):
        self.path = "/"
        self.body = ""
        self.method = ""
        self.params = {}
        self.addr = None
        self.headers = {}
        self._asgi_scope = {}