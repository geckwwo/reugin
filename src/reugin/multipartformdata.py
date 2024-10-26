class MultipartFormDataEntry:
    def __init__(self, data: bytes, content_type: str, name: str, filename: str = None, headers: dict = None):
        self.data = data
        self.content_type = content_type
        self.name = name
        self.filename = filename
        self.headers = headers if headers is not None else {}

    @classmethod
    def from_base(cls, body: bytes, headers: dict):
        assert "content-disposition" in headers, "Content-Disposition is expected"
        content_disp = list(i.strip() for i in headers['content-disposition'].split(";"))
        assert content_disp[0] == "form-data", "Content-Disposition should be form-data"
        cd_attributes = dict(x.strip().split("=") for x in content_disp[1:])
        assert "name" in cd_attributes, "Content-Disposition should have a name attribute"

        name = cd_attributes["name"]
        if name.startswith("\"") and name.endswith("\""):
            name = name[1:-1]

        filename = cd_attributes.get("filename")
        if filename is not None and filename.startswith("\"") and filename.endswith("\""):
            filename = filename[1:-1]

        return cls(body, headers.get("content-type"), name, filename, headers)
    
    def __repr__(self):
        return f"{self.__class__.__name__}({repr(self.name)}, {repr(self.data)})"

def parse_multipart_formdata(headers: dict, body: bytes):
    assert "content-type" in headers, "Content-Type is expected"
    assert headers.get("content-type").split(";")[0].strip().lower() == "multipart/form-data", "Content-Type is not multipart/form-data"
    assert int(headers.get("content-length")) == len(body), "body size is different from content-length"

    ct_attributes = dict(x.strip().split("=") for x in headers.get("content-type").split(";")[1:])
    assert "boundary" in ct_attributes, "multipart/form-data should have boundary attribute in content-type"
    boundary_base = ct_attributes['boundary']
    boundary_start = ("--" + boundary_base).encode()

    entries = body.split(boundary_start)
    print(entries)
    assert entries[0] == b"" and entries[-1] == b"--\r\n", "invalid form data"
    del entries[0]
    del entries[-1]

    entries = [entry[2:-2] for entry in entries]
    entries_with_headers = []
    for entry in entries:
        entry_headers = entry.split(b"\r\n\r\n")[0]
        entry_content = b"\r\n\r\n".join(entry.split(b"\r\n\r\n")[1:])
        entry_headers = (tuple(map(lambda x: x.decode().strip(), header.split(b":", 1))) for header in entry_headers.split(b"\r\n"))
        entry_headers = dict((x.lower(), y) for x, y in entry_headers)

        entries_with_headers.append((entry_content, entry_headers))
    
    return [MultipartFormDataEntry.from_base(entry[0], entry[1]) for entry in entries_with_headers]