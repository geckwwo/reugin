from ..types import ScopeType, SendType, ReceiveType, ReuginPlaceholder

class BaseConnector:
    def __init__(self):
        pass
    async def process_scope(self, scope: ScopeType, receive: ReceiveType, send: SendType, reugin: ReuginPlaceholder) -> bool:
        return False # false equals route was not processed