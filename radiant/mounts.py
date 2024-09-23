from .request import Request
from .response import HTMLResponse, BinaryResponse
from .server import RD_ERR_404
import os
import mimetypes
import warnings

def StaticContent(dir):
    warnings.warn(RuntimeWarning("Static files are experimental and may cause security issues. Windows is known to be vulnerable right now - Unix-like systems should be protected though."))
    async def route(rq: Request, staticrel):
        fp = f"{dir}{'/' if not dir.endswith('/') else ''}{staticrel}"
        if not os.path.isfile(fp):
            return HTMLResponse(404, RD_ERR_404)
        return BinaryResponse(200, mimetypes.guess_type(fp)[0] or "application/octet-stream", open(fp, "rb").read())
    return route