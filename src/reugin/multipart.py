from collections.abc import Mapping

from .types import Headers


class MultipartError(ValueError):
    """The body isn't valid multipart/form-data."""


def _split_unquoted(value: str, separator: str) -> list[str]:
    """Split on `separator`, except inside double quotes. Browsers send `"` in names as %22 and
    leave backslashes alone, so a backslash is an ordinary character here."""
    parts: list[str] = []
    current: list[str] = []
    quoted = False
    for char in value:
        if char == '"':
            quoted = not quoted
        elif char == separator and not quoted:
            parts.append("".join(current))
            current = []
            continue
        current.append(char)
    parts.append("".join(current))
    return parts


def _unquote(value: str) -> str:
    return value[1:-1] if len(value) >= 2 and value[0] == value[-1] == '"' else value


def parse_header_options(value: str) -> tuple[str, dict[str, str]]:
    """Split a header like `form-data; name="file"; filename="a.png"` into its value and options."""
    main, *parts = _split_unquoted(value, ";")
    options: dict[str, str] = {}
    for part in parts:
        key, sep, option = part.strip().partition("=")
        if sep:
            options[key.strip().lower()] = _unquote(option.strip())
    return main.strip().lower(), options


class MultipartEntry:
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
    def from_base(cls, body: bytes, headers: Headers) -> "MultipartEntry":
        if "content-disposition" not in headers:
            raise MultipartError("a part has no Content-Disposition")
        disposition, options = parse_header_options(headers["content-disposition"])
        if disposition != "form-data" or "name" not in options:
            raise MultipartError("a part's Content-Disposition is not form-data with a name")
        content_type = headers.get("content-type", "text/plain")
        return cls(body, content_type, options["name"], options.get("filename"), headers)

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.name!r}, {self.data!r})"


def parse_multipart(headers: Mapping[str, str], body: bytes) -> list[MultipartEntry]:
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

    entries: list[MultipartEntry] = []
    for part in parts[1:-1]:
        part = part.removeprefix(b"\r\n").removesuffix(b"\r\n")
        raw_headers, sep, content = part.partition(b"\r\n\r\n")
        if not sep:
            raise MultipartError("a part has no header block")
        part_headers: Headers = {}
        for line in raw_headers.split(b"\r\n"):
            # Browsers send non-ASCII file and field names as UTF-8.
            try:
                text = line.decode()
            except UnicodeDecodeError:
                text = line.decode("latin-1")
            name, colon, value = text.partition(":")
            if colon:
                part_headers[name.strip().lower()] = value.strip()
        entries.append(MultipartEntry.from_base(content, part_headers))
    return entries
