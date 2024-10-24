from .request import Request
from .response import HTMLResponse, BinaryResponse
from .server import RD_ERR_404
import os
import mimetypes
import warnings
from pathlib import Path

def StaticContent(dir):
    # disable this warning for now - Path used should cover everything
    #warnings.warn(RuntimeWarning("Static files are experimental and may cause security issues. Windows is known to be vulnerable right now - Unix-like systems should be protected though."))
    base_dir = Path(dir).resolve()
    base_path = str(base_dir)
    async def route(rq: Request, staticrel):
        file: Path = (base_dir / staticrel).resolve()
        if not str(file).startswith(base_path):
            # got outside somehow - reject
            return HTMLResponse(404, RD_ERR_404.decode())
        if not file.is_file():
            return HTMLResponse(404, RD_ERR_404.decode())
        return BinaryResponse(200, mimetypes.guess_type(str(file))[0] or "application/octet-stream", file.open("rb").read())
    return route