# Changelog

## 0.3.0

A redesign. The connector stack is gone: routes, WebSocket routes, RPC functions and error pages live in one table on the app. UnjustPython and RPC now work together, so a page's handlers can call the server without hand-written JavaScript. Everything is typed (pyright strict; `py.typed` ships with the package), linted with ruff, and covered by tests. Nothing from 0.2 carries over unchanged; the list below is a map.

### Apps and routes

- `Reugin()` registers everything itself: `@app.get`, `.post`, `.put`, `.patch`, `.delete`, `@app.route(path, methods)`, `@app.websocket`, `@app.rpc`. `HTTPConnector`, `WebSocketConnector`, `RPCConnector`, `BaseConnector`, `app.connect()`, `no_defaults` and `reugin.methods` are gone. Use `app.mount(prefix, asgi_app)` for anything a custom connector did.
- Placeholders have names and types: `/notes/{id:int}` passes `id=12` to the handler by keyword. `{alphanumeric}`, `{path}`, `{filepath}` and `{}` are replaced by `{name}`, `{name:int}` and `{name:path}`.
- More specific routes win, whatever order they were added in: fixed segments, then `int`, then `str`, then `path`.
- A path that has routes, but not for the request's method, answers 405 with `Allow`. GET routes answer HEAD.
- A handler that can't take its route's placeholders fails at registration, not on the first request.
- `@app.error(404)` or `@app.error(SomeException)` registers a page as a normal handler. Error hooks (`@app.errorhook`, with raw ASGI arguments) are gone, and the default error page is a plain HTML document.
- `max_request_body` is a constructor argument: `Reugin(max_request_body=...)`. `app.state` holds anything set up at startup.
- `app.static(prefix, folder)` replaces `reugin.mounts.StaticContent`; the handler class is `reugin.StaticFiles`.

### Requests and responses

- `Request.params` is `Request.query`. `get_body_json()`, `get_body_form()` and `get_body_multipart_formdata()` are `json()`, `form()` and `multipart()`. `RemoteCall` is gone.
- `Request.cookies`, `Request.path_params` and `Request.app` are new; `addr` is `client`.
- `Response(body, status, content_type=..., headers=...)` puts the body first. `HTMLResponse(body, status)` and `JSONResponse(data, status)` follow, and `BinaryResponse` is gone.
- Response headers are a list of pairs, so a name can repeat: `set_cookie()` and `delete_cookie()` use that.
- New: `StreamingResponse` (it stops when the client leaves), `FileResponse` (static files are streamed instead of read whole) and `redirect(url)`, which percent-encodes the URL.
- A header value with a line break is refused (a 500 page) instead of reaching the server. A client that leaves halfway through sending a body gets no response, and the handler doesn't run.
- 204 and 304 responses carry no body and no `Content-Length`.
- `multipartformdata` is `reugin.multipart`; `MultipartFormDataEntry` is `MultipartEntry`. Field and file names are read as UTF-8, and `;` inside quotes no longer splits them.

### UnjustPython and RPC

- `@reugin.jsdef` (no parentheses) translates when the function is defined, so unsupported syntax fails at import and names the line. `UnjustContext`, `build_script()`, `include_file()` and `include_str()` are gone.
- `h.Document` adds a `<script>` with the functions the page uses, the functions they call, and a `fetch` stub for each `@app.rpc` function they call. Its contents are escaped so that `</script>` in a string can't end it.
- Calling a translated function in Python gives a call for an attribute: `onclick=remove(note.id)` renders `onclick="window.remove(12)"`. Attributes go through `window.` so that a function named like an element method (`submit`, `open`, `reset`) isn't shadowed by it.
- New syntax: `async def`, `await`, f-strings, dicts, lambdas, `x if c else y`, `break`, `continue`, `for i in range(...)`, `items[-1]` (as `items.at(-1)`), `len()`, `print()`, `str()`, `int()` (with a base too), `float()`, and `is None`, which also catches `undefined`. Names that are reserved in JavaScript, `await` inside a lambda or comprehension, and builtins used other than called are refused at import.
- Assigned names are declared with `let` at the top of the function, instead of becoming globals on `window`.
- `reugin.browser` provides `document`, `window`, `alert` and other browser names for linters and type checkers, plus `new(...)` for `new`.
- RPC calls are POST requests with a JSON array of arguments at `/_reugin/rpc/<name>` (was `/_reuginpowered_/rpc/<scope>/<name>?args=...`). Requiring JSON keeps other websites from triggering calls. Answers are always `{"ok": ..., "result" | "error": ...}` with a matching status.
- RPC functions take their arguments directly; they get the request only if their first parameter is annotated `Request`.

### WebSockets

- `@app.websocket(path)` handlers take `(ws, **params)`. The connection is accepted on the first `recv()` or `send()`, so raising `HTTPError` before that turns it down.
- At most 32 incoming messages wait for the handler; past that, Reugin stops reading and the client slows down. Cancelling the app (a server shutting down) cancels the handler too.
- `WebSocketConnection` is `WebSocket`, and `WebSocketClosedException` is `WebSocketClosed`. New: `async for message in ws`, `recv_json()` and `send_json()`.

### rhtml

- `<script>` and `<style>` text can't contain `</` or `<!--` that would end the element: they're escaped.
- Children are joined without spaces: `h.p("See ", h.a("docs"), ".")` no longer renders `See  <a>docs</a> .`.
- Lists and generators are accepted as children and flattened.
- `bind` and `tag + tag` are `h.fragment(...)`, and `IncludeString` is `h.raw(...)`. `IncludeFile`, `Property`, `PClass` and `EmptyAttr` are gone: use keyword arguments and `True`.
- `CSSInjection(name, href)` is `h.stylesheet(href)`. `HeadInjection(key, tag)` stays.
- `h.Document(*body, head=..., title=..., **attributes)` takes the body like any tag. It adds a viewport `<meta>`, and event attributes such as `onload=` go on `<body>`.
- Void elements refuse content when the tag is created rather than when it renders.

### Testing

- `reugin.testing.TestClient` drives an app without a server: requests, WebSocket sessions, RPC calls and the lifespan, with a cookie jar.

### Packaging

- Python 3.12 or newer. 0.2.x declared 3.10 but already used syntax that only 3.12 accepts.
- Packaging lives in `pyproject.toml`; `setup.cfg` is gone and `README.MD` is now `README.md`.
- `reugin.types` names: `Scope`, `Receive`, `Send`, `Message`, `ASGIApp`, `JSON`, `Headers` and `LifespanHandler`.

### Fixed

These bugs in 0.2 are gone with the code that had them:

- `import reugin` failed on the main branch: `types`, `connectors` and `response` imported each other.
- Static files: `/static/../static_old/secret.txt` could read from a sibling folder whose name starts with the static folder's name.
- Every WebSocket connection failed: the connector called `match_route` without its routes.
- UnjustPython failed on Python 3.14, which removed `ast.Num` and `ast.Str`. It also turned `//` into a JavaScript comment and didn't escape strings.
- RPC requests whose body arrived in more than one chunk were refused: the size check was inverted.
- Multipart parsing printed every upload to stdout, failed on plain form fields and required `Content-Length`.
- Bad input failed an `assert` (and passed silently under `python -O`); it now gets a 400, 413 or 415.
- Methods Reugin doesn't route, such as `PROPFIND`, got a 500.
- A failing startup or shutdown handler didn't report `lifespan.startup.failed` or `lifespan.shutdown.failed`.
- Route patterns were compiled on every request, and logs went to the root logger instead of `reugin`.
