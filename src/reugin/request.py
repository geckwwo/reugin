import json
from urllib.parse import parse_qsl

from .errors import HTTPError
from .multipartformdata import MultipartError, MultipartFormDataEntry, parse_header_options, parse_multipart_formdata
from .types import JSON, Headers, Scope


def parse_query(query_string: bytes) -> dict[str, str]:
    return dict(parse_qsl(query_string.decode("latin-1"), keep_blank_values=True))


def parse_headers(scope: Scope) -> Headers:
    raw: list[tuple[bytes, bytes]] = scope.get("headers", [])
    return {name.decode("latin-1").lower(): value.decode("latin-1") for name, value in raw}


class Request:
    """An HTTP request, as a route handler gets it."""

    def __init__(self, scope: Scope, body: bytes = b"") -> None:
        self.asgi_scope = scope
        self.method: str = scope.get("method", "GET")
        self.path: str = scope["path"]
        self.params = parse_query(scope.get("query_string", b""))
        """Query string parameters, URL-decoded."""
        self.headers = parse_headers(scope)
        """Header names are lowercase."""
        client: tuple[str, int] | list[str | int] | None = scope.get("client")
        self.addr: tuple[str, int] | None = (str(client[0]), int(client[1])) if client else None
        self.body = body

    def _content_type(self) -> str:
        return parse_header_options(self.headers.get("content-type", ""))[0]

    def get_body_json(self) -> JSON:
        if self._content_type() != "application/json":
            raise HTTPError(415, "Expected application/json")
        try:
            data: JSON = json.loads(self.body)
        except ValueError as e:
            raise HTTPError(400, "Invalid JSON") from e
        return data

    def get_body_form(self) -> dict[str, str]:
        """Fields of a regular HTML form (application/x-www-form-urlencoded)."""
        if self._content_type() != "application/x-www-form-urlencoded":
            raise HTTPError(415, "Expected application/x-www-form-urlencoded")
        return parse_query(self.body)

    def get_body_multipart_formdata(self) -> list[MultipartFormDataEntry]:
        """Fields and files of a form sent with enctype="multipart/form-data"."""
        try:
            return parse_multipart_formdata(self.headers, self.body)
        except MultipartError as e:
            raise HTTPError(400, str(e)) from e
