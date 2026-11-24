"""Names that exist in the browser, for `@jsdef` functions: import them so linters and type checkers
know them. In Python they do nothing; UnjustPython writes them into the JavaScript as they are.

    from reugin.browser import document, new, WebSocket

`new(WebSocket, url)` translates to `new WebSocket(url)`.
"""

from typing import Any

from .unjustpython import JSName

__all__ = [
    "JSON",
    "URL",
    "Array",
    "Date",
    "Math",
    "Number",
    "Object",
    "Promise",
    "String",
    "WebSocket",
    "alert",
    "clearInterval",
    "clearTimeout",
    "confirm",
    "console",
    "document",
    "event",
    "fetch",
    "history",
    "localStorage",
    "location",
    "navigator",
    "new",
    "parseFloat",
    "parseInt",
    "prompt",
    "requestAnimationFrame",
    "sessionStorage",
    "setInterval",
    "setTimeout",
    "window",
]

JSON: Any = JSName("JSON")
Array: Any = JSName("Array")
Date: Any = JSName("Date")
Math: Any = JSName("Math")
Number: Any = JSName("Number")
Object: Any = JSName("Object")
Promise: Any = JSName("Promise")
String: Any = JSName("String")
URL: Any = JSName("URL")
WebSocket: Any = JSName("WebSocket")
alert: Any = JSName("alert")
clearInterval: Any = JSName("clearInterval")
clearTimeout: Any = JSName("clearTimeout")
confirm: Any = JSName("confirm")
console: Any = JSName("console")
document: Any = JSName("document")
event: Any = JSName("event")
"""The event being handled, in an attribute: `onclick=toggle(event)`."""
fetch: Any = JSName("fetch")
history: Any = JSName("history")
localStorage: Any = JSName("localStorage")
location: Any = JSName("location")
navigator: Any = JSName("navigator")
new: Any = JSName("new")
"""`new(Date)` translates to `new Date()`."""
parseFloat: Any = JSName("parseFloat")
parseInt: Any = JSName("parseInt")
prompt: Any = JSName("prompt")
requestAnimationFrame: Any = JSName("requestAnimationFrame")
sessionStorage: Any = JSName("sessionStorage")
setInterval: Any = JSName("setInterval")
setTimeout: Any = JSName("setTimeout")
window: Any = JSName("window")
