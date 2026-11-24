from contextvars import ContextVar

root_path: ContextVar[str] = ContextVar("reugin_root_path", default="")
"""The ASGI root_path of the request being handled, for URLs that pages point back to (RPC calls)."""
