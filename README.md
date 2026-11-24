# Reugin

A small ASGI web framework for Python. Routes, an HTML builder, static files, WebSockets and JSON RPC in about a thousand lines, with no dependencies. Run it with any ASGI server.

```sh
pip install reugin
```

Needs Python 3.12 or newer.

## Hello, world

```py
# server.py
import reugin
import reugin.rhtml as h
from reugin.connectors import HTTPConnector

app = reugin.Reugin()
http = app.connect(HTTPConnector())

@http.get("/")
async def index(req: reugin.Request):
    return h.p("Hello, world!")

@http.get("/hello/{alphanumeric}")
async def hello(req: reugin.Request, name: str):
    return {"hello": name}
```

```sh
uvicorn server:app
```

## Routes

Register handlers with `@http.get`, `.post`, `.put`, `.patch`, `.delete`, `.head`, `.options` or `.trace`, or with `@http.route(path, [methods])` for several methods at once.

Placeholders in the path are passed to the handler in order:

| Placeholder | Matches |
| --- | --- |
| `{alphanumeric}` | letters, digits and `_` |
| `{path}` | the same, plus `/` |
| `{filepath}` | a relative file path without `..` |
| `{any}` or `{}` | anything |

A handler gets a `Request` with `path`, `method`, `params` (the query string), `headers` and `body`, and these readers: `get_body_json()`, `get_body_form()` and `get_body_multipart_formdata()`. It returns one of:

- an `rhtml` tag or a string, sent as HTML;
- a `dict` or a `list`, sent as JSON;
- a `Response` when you need a status code or headers: `HTMLResponse`, `JSONResponse` or `Response` itself for any content type.

Raise `HTTPError` to answer with an error page:

```py
from reugin import HTTPError, JSONResponse

@http.post("/notes")
async def add_note(req: reugin.Request):
    note = req.get_body_json()
    if not note.get("text"):
        raise HTTPError(400, "A note needs some text")
    return JSONResponse(201, {"saved": note["text"]})
```

Unknown paths get a 404 page and unhandled exceptions a 500 page. Request bodies over 256 KiB get a 413 (see `app.max_request_body`).

## Pages that do things

`rhtml` writes HTML as Python, with text escaped: `h.div(h.p("Hi"), class_="card")` renders `<div class="card"><p>Hi</p></div>`. With UnjustPython, small event handlers can be Python too. Reugin translates them to JavaScript, so a whole interactive page stays in one file:

```py
from reugin.unjustpython import UnjustContext

js = UnjustContext()

@js.jsdef()
def greet():
    alert("Hello from Python!")

@http.get("/hi")
async def hi(req: reugin.Request):
    return h.Document([h.button("Say hi", onclick=greet), js.build_script()])
```

UnjustPython covers a small subset of Python: calls, arithmetic, comparisons, `if`, `for`, `while` and list comprehensions. Anything else raises an error that names it.

## Also included

- **Static files**: `http.get("/static/{filepath}")(reugin.mounts.StaticContent("static"))`.
- **WebSockets**: `ws = app.connect(WebSocketConnector())`, then `@ws.route("/chat")` on an `async def chat(conn)` that loops over `await conn.recv()` and `await conn.send(...)`.
- **RPC**: functions registered with `@rpc.rpc()` on an `RPCConnector("api")` are called at `/_reuginpowered_/rpc/api/<name>?args=[1,2]` and answer in JSON.
- **Startup and shutdown**: `@app.on_startup` and `@app.on_shutdown` run async functions when the server starts and stops.

## How it works

A Reugin app is a stack of connectors. Each ASGI event goes through them in priority order (lowest number first), and the first one that handles it answers. `HTTPConnector`, `WebSocketConnector` and `RPCConnector` are connectors, and so are the built-in 404 page and lifespan handling. To add your own, subclass `BaseConnector` and pass it to `app.connect(connector, priority)`. Error pages work the same way, through `@app.errorhook(priority)`.

## Development

```sh
uv sync
uv run python -m unittest
uv run pyright
uv run ruff check
```

## License

BSD 3-Clause. See [LICENSE](LICENSE).
