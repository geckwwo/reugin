class BaseConnector:
    def __init__(self):
        pass
    async def process_scope(self, asgi_scope, receive, send, reugin):
        return False # false equals route was not processed