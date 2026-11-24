from collections.abc import Mapping
from http import HTTPStatus


def status_phrase(status: int) -> str:
    try:
        return HTTPStatus(status).phrase
    except ValueError:
        return "Error"


class HTTPError(Exception):
    """Raise from a route to answer with an error status: the app's page for that status, or Reugin's.

    Reugin raises it too: 400 for a body it can't parse, 404 and 405 for routes it doesn't have,
    413 for a body over `max_request_body`, 415 for the wrong content type.
    """

    def __init__(self, status: int, detail: str | None = None, headers: Mapping[str, str] | None = None) -> None:
        detail = detail or status_phrase(status)
        super().__init__(status, detail)
        self.status = status
        self.detail = detail
        self.headers = dict(headers or {})
        """Added to the error response, such as `Allow` on a 405."""
