# Reugin

A small ASGI web framework for Python, for interactive pages that live in one file. Pages are built from Python calls, their click handlers are Python functions that Reugin translates to JavaScript, and those handlers can call `async` functions on the server directly. No dependencies. Run it with any ASGI server.

```sh
pip install reugin
```

Needs Python 3.12 or newer.

## A whole tool

```py
# notes.py
import reugin
import reugin.rhtml as h
from reugin.browser import document, location

app = reugin.Reugin()
notes: list[str] = []


@app.rpc
async def add_note(text: str) -> None:
    notes.append(text)


@reugin.jsdef
async def submit():
    await add_note(document.getElementById("note").value)
    location.reload()


@app.get("/")
async def index(req: reugin.Request):
    return h.Document(
        h.ul(h.li(note) for note in notes),
        h.input(id="note"),
        h.button("Add", onclick=submit),
        title="Notes",
    )
```

```sh
uvicorn notes:app
```

`submit` runs in the browser. Reugin translates it when the module loads and puts it in the page, along with a `fetch` for `add_note`.

## Routes

```py
@app.get("/notes/{id:int}")
async def note(req: reugin.Request, id: int):
    if id >= len(notes):
        raise reugin.HTTPError(404)
    return h.p(notes[id])
```

Register handlers with `@app.get`, `.post`, `.put`, `.patch` and `.delete`, or `@app.route(path, ["GET", "POST"])`. Placeholders are passed by name:

| Placeholder | Matches |
| --- | --- |
| `{name}` | one path segment, as a `str` |
| `{id:int}` | digits, as an `int` |
| `{rest:path}` | one or more segments, without `..` |

When several routes match, the more specific one wins: `/notes/new` before `/notes/{id:int}` before `/notes/{name}`. A path with routes for other methods answers 405, and GET routes answer HEAD too.

A handler gets a `Request` with `method`, `path`, `query`, `headers`, `cookies`, `body` and `path_params`, and these readers: `json()`, `form()` and `multipart()`. It returns one of:

- an `rhtml` tag or a string, sent as HTML;
- a `dict` or a `list`, sent as JSON;
- a `Response` for anything else: `HTMLResponse`, `JSONResponse`, `StreamingResponse`, `FileResponse`, `redirect(url)`, or `Response(body, status, content_type=...)`. A streaming response stops when the client leaves.

Responses can `set_cookie()` and `delete_cookie()`. Bodies over 256 KiB get a 413: see `Reugin(max_request_body=...)`.

## Error pages

Raise `HTTPError(status, detail)` from anywhere in a handler. Pages for an error status or an exception type are handlers too:

```py
@app.error(404)
async def not_found(req: reugin.Request, error: reugin.HTTPError):
    return h.Document(h.h1("Nothing here"), h.a("Back to the notes", href="/"))


@app.error(KeyError)
async def missing(req: reugin.Request, error: KeyError):
    return {"missing": str(error)}
```

Unhandled exceptions are logged to the `reugin` logger and answered with the 500 page.

## rhtml

```py
h.div(h.p("Hi"), class_="card")   # <div class="card"><p>Hi</p></div>
h.ul(h.li(n) for n in names)      # lists and generators are flattened
h.input(disabled=True, value=None) # <input disabled>
```

Text and attribute values are escaped; `h.raw(markup)` isn't. The text of `h.script` and `h.style` is kept as written, except that `</` can't close the element early. `data_id=5` renders `data-id="5"`, `None` and `False` leave things out, and `h.fragment(...)` groups tags without a wrapper. `h.Document(*body, title=..., head=[...], lang="en")` makes a page. A component can ask for a stylesheet with `h.stylesheet("/static/card.css")`, which lands in `<head>` once, however many times it's used.

## UnjustPython

`@reugin.jsdef` translates a small subset of Python to JavaScript: calls, attributes, arithmetic, comparisons, `and`/`or`/`not`, `if`, `for` (including `range`), `while`, f-strings, lists, dicts, list comprehensions, lambdas, `async def` and `await`. Anything else fails when the module loads, naming the line.

- Use a function as an attribute (`onclick=save`) or call it with arguments (`onclick=remove(note.id)`); the arguments are written as JSON. Attributes call it as `window.save()`, so a function named `submit` or `open` doesn't clash with the element's own methods.
- Functions it calls, other `@jsdef` functions and `@app.rpc` functions, are added to the page with it.
- Browser names such as `document`, `window`, `alert` and `fetch` come from `reugin.browser`, so linters know them. `new(WebSocket, url)` is `new WebSocket(url)`.
- `len(x)`, `print(...)`, `str(x)`, `int(x)`, `int(x, base)` and `float(x)` translate to their JavaScript counterparts; `range` works in a `for` loop.
- It's a translation, not an emulation: JavaScript semantics apply. Lists have `push`, not `append`, and `+` on two lists joins them as text.

## RPC

```py
@app.rpc
async def rename(req: reugin.Request, before: str, after: str) -> bool:
    ...
```

The browser calls an RPC function with `POST /_reugin/rpc/<name>` and a JSON array of arguments, and gets `{"ok": true, "result": ...}` or `{"ok": false, "error": "..."}`. Inside a `@jsdef` function that's just `await rename("a", "b")`. Functions whose first parameter is a `Request` get the call's request. Because calls must be JSON POSTs, other websites can't trigger them from a visitor's browser.

## WebSockets

```py
@app.websocket("/rooms/{room}")
async def chat(ws: reugin.WebSocket, room: str):
    async for message in ws:
        await ws.send(f"{room}: {message}")
```

The connection is accepted on the first `recv()` or `send()`. Raising `HTTPError` before that turns it down. `recv_json()` and `send_json()` handle JSON. Up to 32 messages wait for a handler that isn't reading; after that the client has to wait.

## Also included

- **Static files:** `app.static("/static", "static")`.
- **Other ASGI apps:** `app.mount("/admin", other_app)` hands over everything under `/admin`.
- **Startup and shutdown:** `@app.on_startup` and `@app.on_shutdown`, with `app.state` for what they set up (`req.app.state` in a handler).
- **Tests:** `reugin.testing.TestClient` runs requests, WebSocket sessions and RPC calls without a server:

```py
async with TestClient(app) as client:
    await client.rpc(add_note, "Buy milk")
    res = await client.get("/")
    assert "Buy milk" in res.text
```

## Development

```sh
uv sync
uv run python -m unittest
uv run pyright
uv run ruff check
```

Some tests run translated JavaScript in Node.js and are skipped without it.

## License

BSD 3-Clause. See [LICENSE](LICENSE).
