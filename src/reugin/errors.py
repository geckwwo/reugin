from http import HTTPStatus


class HTTPError(Exception):
    """Raise from a route to answer with an error status and Reugin's error page.

    Reugin raises it too: 400 for a body it can't parse, 413 for a body over
    `Reugin.max_request_body`, 415 for the wrong content type.
    """

    def __init__(self, status: int, detail: str | None = None) -> None:
        if detail is None:
            try:
                detail = HTTPStatus(status).phrase
            except ValueError:
                detail = "Error"
        super().__init__(status, detail)
        self.status = status
        self.detail = detail
