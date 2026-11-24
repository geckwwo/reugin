from collections.abc import Mapping

from .types import Headers


class MultipartError(ValueError):
    """The body isn't valid multipart/form-data."""


def parse_header_options(value: str) -> tuple[str, dict[str, str]]:
    """Split a header like `form-data; name="file"; filename="a.png"` into its value and options."""
    main, *parts = value.split(";")
    options: dict[str, str] = {}
    for part in parts:
        key, sep, option = part.strip().partition("=")
        if not sep:
            continue
        option = option.strip()
        if len(option) >= 2 and option[0] == option[-1] == '"':
            option = option[1:-1]
        options[key.strip().lower()] = option
    return main.strip().lower(), options


class MultipartFormDataEntry:
    """One field of a multipart/form-data body: a form value or an uploaded file."""

    def __init__(
        self,
        data: bytes,
        content_type: str,
        name: str,
        filename: str | None = None,
        headers: Headers | None = None,
    ) -> None:
        self.data = data
        self.content_type = content_type
        self.name = name
        self.filename = filename
        self.headers: Headers = headers if headers is not None else {}

    @property
    def text(self) -> str:
        return self.data.decode()

    @classmethod
    def from_base(cls, body: bytes, headers: Headers) -> "MultipartFormDataEntry":
        if "content-disposition" not in headers:
            raise MultipartError("a part has no Content-Disposition")
        disposition, options = parse_header_options(headers["content-disposition"])
        if disposition != "form-data" or "name" not in options:
            raise MultipartError("a part's Content-Disposition is not form-data with a name")
        content_type = headers.get("content-type", "text/plain")
        return cls(body, content_type, options["name"], options.get("filename"), headers)

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.name!r}, {self.data!r})"


def parse_multipart_formdata(headers: Mapping[str, str], body: bytes) -> list[MultipartFormDataEntry]:
    """Parse a multipart/form-data body. `headers` are the request's, with lowercase names."""
    content_type, options = parse_header_options(headers.get("content-type", ""))
    if content_type != "multipart/form-data":
        raise MultipartError("Content-Type is not multipart/form-data")
    if not options.get("boundary"):
        raise MultipartError("Content-Type has no boundary")

    parts = body.split(b"--" + options["boundary"].encode("latin-1"))
    # parts[0] is the preamble; the last part starts with the closing "--".
    if len(parts) < 2 or not parts[-1].startswith(b"--"):
        raise MultipartError("the body does not end with the closing boundary")

    entries: list[MultipartFormDataEntry] = []
    for part in parts[1:-1]:
        part = part.removeprefix(b"\r\n").removesuffix(b"\r\n")
        raw_headers, sep, content = part.partition(b"\r\n\r\n")
        if not sep:
            raise MultipartError("a part has no header block")
        part_headers: Headers = {}
        for line in raw_headers.split(b"\r\n"):
            name, colon, value = line.decode("latin-1").partition(":")
            if colon:
                part_headers[name.strip().lower()] = value.strip()
        entries.append(MultipartFormDataEntry.from_base(content, part_headers))
    return entries
