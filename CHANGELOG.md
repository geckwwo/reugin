# Changelog

## 0.3.0

A tidy-up of the whole codebase: everything is typed (pyright strict, `py.typed` ships with the package), linted with ruff and covered by tests. Some of it needed breaking changes, listed first.

### Breaking changes

- Python 3.12 or newer. 0.2.x declared 3.10 but already used syntax that only 3.12 accepts.
- Packaging lives in `pyproject.toml`; `setup.cfg` is gone and `README.MD` is now `README.md`.
- `Request(scope, body)` builds itself from the ASGI scope; it used to be created empty and filled in by the connector.
- `Request.params` values are URL-decoded, and a parameter without `=` no longer breaks the request.
- `RemoteCall.body` is `bytes`, like `Request.body` (it was a `str`).
- Bad input gets an error page instead of failing an `assert` (asserts disappear under `python -O`): 400 for invalid JSON or multipart data, 413 for a body over `max_request_body`, 415 for the wrong content type.
- A route that returns an unsupported type raises `TypeError` (it was an `AssertionError`); both end as a 500.
- `Response` takes a `str` or `bytes` body, so `BinaryResponse` is now only an alias. Every response sends `content-length`, and HTML is sent as `text/html; charset=utf-8`.
- `Reugin.connectors` and `Reugin.errorhooks` are lists of `(priority, item)` pairs instead of dicts of lists.
- `reugin.types` names: `Scope`, `Receive`, `Send`, `Message`, `JSON`, `Headers` and `LifespanHandler` replace `ScopeType`, `ReceiveType`, `SendType` and friends. `ReuginPlaceholder` is gone.
- `BaseConnector` is abstract: subclasses must implement `process_scope`.
- rhtml:
  - `Tag.rdbody` and `Tag.rdattributes` are `Tag.children` and `Tag.attributes`. Attributes are no longer copied onto the tag object.
  - In keyword arguments a trailing `_` is dropped and `_` becomes `-`: `class_="card"`, `data_id=5` → `data-id="5"`.
  - Attribute values are fully escaped. `None` and `False` leave the attribute out; `True` renders it without a value.
  - `None` and booleans in the content render nothing (they used to print `None`, `True`).
  - Void elements (`img`, `input`, `meta`, `link`, `br` and the rest) have no closing tag and refuse content.
  - `<script>` and `<style>` content is no longer HTML-escaped, so `a < b` survives.
  - A tag without attributes renders as `<p>`, not `<p >`.
  - `Document` renders `<html>` and `<meta charset="utf-8">`, and takes attributes such as `lang="en"`.
- WebSockets (the connector never worked in 0.2, so no existing code relies on these): `WebSocketConnector.connect(path)` is `.route(path)`; `recv()` returns every queued message and then raises `WebSocketClosedException`; `is_closed()` is the `closed` property; `close()` sends an empty reason by default.
- RPC: an unknown name under the RPC prefix gets a JSON 404 instead of the HTML 404 page. Arguments are checked against the function's signature before the call, so a `TypeError` raised inside the function is a 500, not a 400.
- UnjustPython: `jsdef` returns a `JSFunction` instead of a stub with a magic attribute, and `generate_js_code(source)` drops its unused name argument. `//` raises `NotImplementedError` (it was translated into a JavaScript comment). Arithmetic is wrapped in parentheses, so precedence carries over.
- Multipart fields without a `Content-Type` get `text/plain`.

### Fixed

- `import reugin` failed on the main branch: `types`, `connectors` and `response` imported each other.
- Static files: `/static/../static_old/secret.txt` could read from a sibling folder whose name starts with the static folder's name. The resolved path must now be inside the folder, and `{filepath}` rejects `..`.
- Every WebSocket connection failed: the connector called `match_route` without its routes.
- UnjustPython failed on Python 3.14, which removed `ast.Num` and `ast.Str`. Strings are now escaped for JavaScript.
- RPC requests whose body arrived in more than one chunk were refused: the size check was inverted.
- Multipart parsing printed every upload to stdout, failed on plain form fields (no `Content-Type`), and required `Content-Length`. Quoted boundaries and `=` inside values now parse.
- HTTP methods Reugin doesn't route, such as `PROPFIND`, got a 500; they get a 404.
- The default 500 hook sent an HTTP response for WebSocket errors. A failing WebSocket handler now closes the connection with 1011, and the error is logged.
- WebSocket requests to unknown paths are refused (closed before accepting) instead of raising `NotImplementedError`.
- A failing startup or shutdown handler reports `lifespan.startup.failed` or `lifespan.shutdown.failed`.
- Route patterns are compiled once instead of on every request.
- Static files are read in a worker thread instead of blocking the event loop.
- Logs go to the `reugin` logger instead of the root logger.

### Added

- `HTTPError(status, detail)`, to answer with an error page from a route.
- `Request.get_body_form()` for regular HTML forms.
- `@app.on_startup` and `@app.on_shutdown`.
- Around 90 standard HTML tags in `rhtml`, from `a` to `wbr`.
- `MultipartFormDataEntry.text`.
- UnjustPython: `not`, `and`, `or`, `while`, `+=`, `None`, `pass` and list literals. Anything unsupported raises `NotImplementedError` naming the construct.
- A test suite (`python -m unittest`) and strict pyright and ruff settings in `pyproject.toml`.
