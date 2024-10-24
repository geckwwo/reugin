# Reugin
Reugin is an ASGI framework, made for quick, simple and manageable HTTP server code. Reugin is light-weight, has no dependencies and requires only an ASGI-compatible web server to start an application.

# Example usage
Save this code into `server.py`
```py
import reugin
import reugin.rhtml as h

app = reugin.Reugin()
http = app.connect(reugin.connectors.http.HTTPConnector())

@http.route("/")
async def root_route(req: reugin.Request):
    return h.p("Hello, world")
```
and run this with any ASGI server (for example, Uvicorn):
> $ uvicorn server:app

.. where `server` is the filename, and `app` is the `reugin.Reugin` instance.

# Licensing
This project is licensed under BSD 3-clause licese. See LICENSE file for more.