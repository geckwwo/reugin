import inspect
import json
import shutil
import subprocess
import tempfile
import unittest
from collections.abc import Callable

import reugin.rhtml as h
from reugin import HTTPError, JSFunction, Request, Reugin, jsdef
from reugin.browser import Date, alert, document, event, new
from reugin.rpc import takes_request
from reugin.testing import TestClient
from reugin.types import JSON
from reugin.unjustpython import page_script, translate

NODE = shutil.which("node")


def run_js(code: str, expression: str) -> JSON:
    """Evaluate `expression` after `code` in Node and return its (awaited) value."""
    assert NODE is not None
    script = f"{code}\nPromise.resolve({expression}).then(value => console.log(JSON.stringify(value ?? null)))"
    out = subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=True, timeout=10).stdout
    data: JSON = json.loads(out)
    return data


def node_check(code: str) -> None:
    assert NODE is not None
    with tempfile.NamedTemporaryFile("w", suffix=".js") as file:
        file.write(code)
        file.flush()
        subprocess.run([NODE, "--check", file.name], check=True, capture_output=True, timeout=10)


@jsdef
def total(items: list[int | None]) -> int:
    result = 0
    for item in items:
        if item is None:
            continue
        result += item
    return result


@jsdef
def describe(name: str, count: int) -> str:
    label = "item" if count == 1 else "items"
    return f"{name} has {count} {label} `{{ok}}` ${{no}}"


@jsdef
def evens(numbers: list[int]) -> list[int]:
    return [n * 10 for n in numbers if n % 2 == 0 and n > 0]


@jsdef
def shapes() -> dict[str, object]:
    ys = [1, 2, 3]
    point: dict[str, object] = {"x": 1, "y": ys, "nested": {"ok": True, "none": None}}
    point["z"] = len(ys)
    return point


@jsdef
def fizz(n: int) -> str:
    """Docstrings are left out."""
    i = 1
    out = ""
    while i <= n:
        if not i % 15:
            out += "FizzBuzz"
        elif i % 3 == 0:
            out += "Fizz"
        else:
            out += str(i)
        i += 1
    return out


@jsdef
def twice(x: float) -> float:
    double: Callable[[float], float] = lambda y: y * 2  # noqa: E731
    return double(double(x)) + int(2.7) - 2**3 / 4


@jsdef
def present(value: object) -> bool:
    return value is not None and value != ""


@jsdef
async def slow_double(x: int) -> int:
    return await helper(x) * 2


@jsdef
async def helper(x: int) -> int:
    return x


async def g(x: int) -> int:
    return x


@jsdef
def greet() -> None:
    alert(f"Hello {document.title}")


@jsdef
def remove(note_id: int | str) -> None:
    alert(note_id)


@jsdef
def toggle(e: object) -> None:
    alert(e)


@jsdef
def script_end() -> str:
    return "</script><!--"


@jsdef
def count_down(start: int, stop: int) -> str:
    out = ""
    for i in range(start, stop, -2):
        out += str(i)
    for j in range(2, 5):
        out += str(j)
    return out + str([7, 8, 9][-1])


@jsdef
def as_objects(ids: list[int]) -> list[dict[str, int]]:
    return [{"id": n} for n in ids]


@jsdef
def empty() -> dict[str, int]:
    make: Callable[[], dict[str, int]] = lambda: {}  # noqa: E731
    return make()


@jsdef
def negative_square(a: int) -> int:
    return (-a) ** 2


@jsdef
def from_hex(text: str) -> int:
    return int(text, 16)


@jsdef
def submit() -> None:
    alert("mine, not the form's")


@jsdef
def run_later(callback: object) -> None:
    alert(callback)


@jsdef
def make_date() -> object:
    return new(Date, 2020, 1, 1)


class TranslatorTest(unittest.TestCase):
    def test_statements(self) -> None:
        self.assertEqual(translate("x = 1 + 2 * 3"), "x = (1 + (2 * 3));")
        self.assertEqual(translate("f(a.b[0], 'x\"y')"), 'f(a.b[0], "x\\"y");')

    def test_locals_are_declared(self) -> None:
        self.assertIn("function total(items) { let result, item;", total.code)

    def test_unsupported_syntax_fails_at_definition(self) -> None:
        with self.assertRaises(NotImplementedError) as caught:

            @jsdef
            def bad() -> None:
                with open("notes.txt"):
                    pass

        lines, start = inspect.getsourcelines(TranslatorTest.test_unsupported_syntax_fails_at_definition)
        line = start + next(i for i, text in enumerate(lines) if text.strip().startswith("with open"))
        self.assertEqual(str(caught.exception), f"UnjustPython, line {line}: With is not supported")
        with self.assertRaises(NotImplementedError):

            @jsdef
            def unpack() -> None:
                a, b = 1, 2
                alert(a + b)

    def test_more_unsupported_code(self) -> None:
        def lambda_await() -> None:
            @jsdef
            async def f(items: list[int]) -> list[object]:
                return [await g(x) for x in items]

        def reserved_lambda() -> None:
            @jsdef
            def f(items: list[int]) -> list[int]:
                return list(map(lambda default: default, items))

        def reserved_comprehension() -> None:
            @jsdef
            def f(items: list[int]) -> list[int]:
                return [this for this in items]

        def reserved_nested() -> None:
            @jsdef
            def f() -> None:
                def switch() -> None:
                    pass

                switch()

        def range_value() -> None:
            @jsdef
            def f(n: int) -> list[int]:
                return [i * 2 for i in range(n)]

        def assign_last() -> None:
            @jsdef
            def f(items: list[int]) -> None:
                items[-1] = 0

        def len_value() -> None:
            @jsdef
            def f() -> object:
                return len

        for case in (
            lambda_await,
            reserved_lambda,
            reserved_comprehension,
            reserved_nested,
            range_value,
            assign_last,
            len_value,
        ):
            with self.subTest(case.__name__), self.assertRaises(NotImplementedError):
                case()

    def test_handlers_are_called_through_window(self) -> None:
        # A bare `submit()` in a form's button would call form.submit() instead.
        rendered = str(h.form(h.button(onclick=submit)))
        self.assertEqual(rendered, '<form><button onclick="window.submit()"></button></form>')

    def test_range_steps_must_be_numbers(self) -> None:
        with self.assertRaises(NotImplementedError):

            @jsdef
            def stepped(step: int) -> None:
                for i in range(0, 10, step):
                    alert(i)

    def test_reserved_names(self) -> None:
        with self.assertRaises(ValueError):

            @jsdef
            def delete() -> None:
                pass

        with self.assertRaises(NotImplementedError):

            @jsdef
            def uses_this(this: int) -> int:
                return this

    def test_calls_from_python(self) -> None:
        self.assertEqual(remove(12).code, "window.remove(12)")
        self.assertEqual(remove('a"b').code, 'window.remove("a\\"b")')
        self.assertEqual(toggle(event).code, "window.toggle(event)")
        self.assertEqual(
            str(h.button(onclick=remove('a"b'))), '<button onclick="window.remove(&quot;a\\&quot;b&quot;)"></button>'
        )
        with self.assertRaises(TypeError):
            remove(note_id=1)

    def test_page_includes_what_it_uses(self) -> None:
        page = h.Document(h.button(onclick=greet), h.button(onclick=greet), h.a(onclick=slow_double(2)))
        rendered = str(page)
        self.assertEqual(rendered.count("function greet()"), 1)
        self.assertIn("async function helper(x)", rendered)
        self.assertNotIn("function fizz", rendered)
        rendered = str(h.Document(h.button(onclick=run_later(greet))))
        self.assertIn('onclick="window.run_later(greet)"', rendered)
        self.assertIn("function greet()", rendered)

    def test_two_functions_with_one_name(self) -> None:
        def make() -> JSFunction[[]]:
            @jsdef
            def greet() -> None:
                pass

            return greet

        with self.assertRaises(ValueError):
            str(h.Document(h.button(onclick=greet), h.button(onclick=make())))

    def test_script_cannot_end_early(self) -> None:
        code = page_script([script_end])
        self.assertNotIn("</script>", code)
        self.assertNotIn("<!--", code)


@unittest.skipUnless(NODE, "needs Node.js")
class BehaviourTest(unittest.TestCase):
    """Translated functions give the same results in JavaScript as in Python."""

    def test_same_results(self) -> None:
        cases: list[tuple[JSFunction[...], list[JSON]]] = [
            (total, [[1, None, 2, 3]]),
            (describe, ["Ada", 1]),
            (describe, ["Bob", 3]),
            (evens, [[-2, 0, 1, 2, 3, 4]]),
            (shapes, []),
            (fizz, [15]),
            (count_down, [9, 2]),
            (as_objects, [[1, 2]]),
            (empty, []),
            (negative_square, [3]),
            (from_hex, ["ff"]),
            (twice, [1.5]),
            (present, [None]),
            (present, [""]),
            (present, [0]),
        ]
        for fn, args in cases:
            with self.subTest(fn.name, args=args):
                expected = fn.fn(*args)
                self.assertEqual(run_js(fn.code, f"{fn.name}(...{json.dumps(args)})"), expected)

    def test_async_and_await(self) -> None:
        self.assertEqual(run_js(page_script([slow_double]), "slow_double(21)"), 42)

    def test_escaped_script_still_works(self) -> None:
        self.assertEqual(run_js(page_script([script_end]), "script_end()"), "</script><!--")

    def test_new(self) -> None:
        self.assertEqual(run_js(page_script([make_date]), "make_date().getFullYear()"), 2020)


def make_rpc_app() -> Reugin:
    app = Reugin()

    @app.rpc
    async def add(a: int, b: int) -> int:
        return a + b

    @app.rpc
    async def whoami(req: Request, greeting: str) -> str:
        return f"{greeting}, {req.headers.get('x-user', 'stranger')}"

    @app.rpc
    async def fail() -> None:
        raise RuntimeError("no")

    @app.rpc
    async def refuse() -> None:
        raise HTTPError(403, "Not yours")

    @jsdef
    async def save() -> None:
        alert(await add(1, 2))

    @app.get("/")
    async def index(req: Request) -> h.Tag:
        return h.Document(h.button("Save", onclick=save))

    return app


class RPCTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.app = make_rpc_app()
        self.client = TestClient(self.app)

    async def call(self, name: str, *args: JSON) -> tuple[int, JSON]:
        res = await self.client.rpc(self.app.rpcs[name], *args)
        return res.status, res.json()

    async def test_calls(self) -> None:
        self.assertEqual(await self.call("add", 2, 3), (200, {"ok": True, "result": 5}))
        self.assertEqual(await self.call("whoami", "Hi"), (200, {"ok": True, "result": "Hi, stranger"}))
        self.assertEqual(await self.app.rpcs["add"](1, 1), 2)

    async def test_errors(self) -> None:
        self.assertEqual((await self.call("add", 1))[0], 400)
        self.assertEqual(await self.call("refuse"), (403, {"ok": False, "error": "Not yours"}))
        with self.assertLogs("reugin", "ERROR"):
            self.assertEqual(await self.call("fail"), (500, {"ok": False, "error": "Internal Server Error"}))
        res = await self.client.post("/_reugin/rpc/nope", json=[])
        self.assertEqual(res.status, 404)
        self.assertEqual((await self.client.post("/_reugin/rpc/add", json={"a": 1})).status, 400)
        res = await self.client.post("/_reugin/rpc/add", body="[1, 2]", headers={"content-type": "text/plain"})
        self.assertEqual(res.status, 415)

    async def test_only_post(self) -> None:
        res = await self.client.get("/_reugin/rpc/add?args=[1,2]")
        self.assertEqual((res.status, res.header("allow")), (405, "POST"))

    async def test_duplicate_names(self) -> None:
        with self.assertRaises(ValueError):

            @self.app.rpc
            async def add() -> None:
                pass

    async def test_page_calls_the_rpc(self) -> None:
        page = (await self.client.get("/")).text
        self.assertIn('function add(...args) { return __reugin_rpc("/_reugin/rpc/add", args); }', page)
        self.assertIn("async function save() { alert((await add(1, 2))); }", page)
        if NODE:
            node_check(page.split("<script>")[1].split("</script>")[0])

    async def test_mounted_app_points_at_its_prefix(self) -> None:
        outer = Reugin()
        outer.mount("/tools", self.app)
        page = (await TestClient(outer).get("/tools/")).text
        self.assertIn('"/tools/_reugin/rpc/add"', page)

    def test_request_annotation_as_text(self) -> None:
        kind = inspect.Parameter.POSITIONAL_OR_KEYWORD
        as_text = inspect.Signature([inspect.Parameter("req", kind, annotation="reugin.Request")])
        as_class = inspect.Signature([inspect.Parameter("req", kind, annotation=Request)])
        plain = inspect.Signature([inspect.Parameter("x", kind, annotation=int)])
        self.assertTrue(takes_request(as_text))
        self.assertTrue(takes_request(as_class))
        self.assertFalse(takes_request(plain))


class BrowserNamesTest(unittest.TestCase):
    def test_names(self) -> None:
        self.assertEqual(document.body.style.path, "document.body.style")
        with self.assertRaises(RuntimeError):
            alert("hi")
