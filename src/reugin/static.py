from pathlib import Path

from .errors import HTTPError
from .request import Request
from .response import FileResponse


class StaticFiles:
    """A route handler that serves the files in a folder. `app.static("/static", "static")` sets one up;
    by hand it's `app.get("/static/{path:path}")(StaticFiles("static"))`.
    """

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory).resolve()
        if not self.directory.is_dir():
            raise ValueError(f"StaticFiles: {directory} is not a folder")

    async def __call__(self, req: Request, path: str) -> FileResponse:
        file = (self.directory / path).resolve()
        # The resolved path must stay inside the folder: this also catches symlinks out of it, and
        # sibling folders whose names start with the same letters ("static" and "static_old").
        if not file.is_relative_to(self.directory) or not file.is_file():
            raise HTTPError(404)
        return FileResponse(file)
