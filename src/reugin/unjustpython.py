"""UnjustPython: small Python functions translated to JavaScript, for the event handlers of rhtml pages.

    from reugin.browser import alert

    @reugin.jsdef
    def greet(name):
        alert(f"Hello, {name}!")

    page = h.Document(h.button("Hi", onclick=greet("Ada")))

The function is translated when it's defined, so anything unsupported fails at import, naming the
line. `h.Document` adds a <script> with the functions its attributes use, the functions those call,
and a `fetch` for every `@app.rpc` function they call.

It covers a small, readable subset of Python: calls, attributes, arithmetic, comparisons, `and`/`or`/`not`,
`if`/`for`/`while`, f-strings, lists, dicts, list comprehensions, lambdas, `async def` and `await`.
"""

import ast
import inspect
import json
import textwrap
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Iterator
from typing import Any, Never

BINARY_OPERATORS: dict[type[ast.operator], str] = {
    ast.Add: "+",
    ast.Sub: "-",
    ast.Mult: "*",
    ast.Div: "/",
    ast.Mod: "%",
    ast.Pow: "**",
}
COMPARISONS: dict[type[ast.cmpop], str] = {
    ast.Eq: "===",
    ast.NotEq: "!==",
    ast.Lt: "<",
    ast.LtE: "<=",
    ast.Gt: ">",
    ast.GtE: ">=",
    ast.Is: "===",
    ast.IsNot: "!==",
}
UNARY_OPERATORS: dict[type[ast.unaryop], str] = {ast.Not: "!", ast.USub: "-", ast.UAdd: "+"}
BOOLEAN_OPERATORS: dict[type[ast.boolop], str] = {ast.And: "&&", ast.Or: "||"}
BUILTINS = {"str": "String", "float": "Number", "int": "Math.trunc"}
"""Python builtins that translate when called with one argument. `print(...)` is `console.log(...)`,
`len(x)` is `x.length` and `int(x, base)` is `parseInt(x, base)`."""
PYTHON_ONLY = frozenset({"len", "print", "range", *BUILTINS})

JS_RESERVED = frozenset(
    (
        "await",
        "break",
        "case",
        "catch",
        "class",
        "const",
        "continue",
        "debugger",
        "default",
        "delete",
        "do",
        "else",
        "enum",
        "export",
        "extends",
        "false",
        "finally",
        "for",
        "function",
        "if",
        "implements",
        "import",
        "in",
        "instanceof",
        "interface",
        "let",
        "new",
        "null",
        "package",
        "private",
        "protected",
        "public",
        "return",
        "static",
        "super",
        "switch",
        "this",
        "throw",
        "true",
        "try",
        "typeof",
        "var",
        "void",
        "while",
        "with",
        "yield",
    )
)


def check_js_name(name: str) -> str:
    if name in JS_RESERVED:
        raise ValueError(f"{name!r} is a reserved word in JavaScript: give the function another name")
    return name


class JSObject(ABC):
    """Something a page's script defines by name: a translated function, or the stub of an RPC function."""

    name: str

    @abstractmethod
    def js_code(self) -> str: ...

    def js_dependencies(self) -> Iterable["JSObject"]:
        """Other definitions this one needs on the page."""
        return ()


class JSName:
    """A name that only exists in the browser, such as `document`. See `reugin.browser`.

    Attributes chain (`document.body`); passed to a JavaScript call, it's written as is: `toggle(event)`.
    """

    def __init__(self, path: str) -> None:
        self.path = path

    def __getattr__(self, attribute: str) -> "JSName":
        if attribute.startswith("__"):
            raise AttributeError(attribute)
        return JSName(f"{self.path}.{attribute}")

    def __call__(self, *args: object, **kwargs: object) -> Never:
        raise RuntimeError(f"{self.path} exists in the browser, not in Python")

    def __repr__(self) -> str:
        return f"JSName({self.path!r})"


def js_value(value: object) -> str:
    if isinstance(value, JSName):
        return value.path
    if isinstance(value, JSFunction):
        return value.name
    return json.dumps(value, ensure_ascii=False)


class JSCall:
    """A call of a translated function with arguments from Python, as an attribute value:
    `onclick=remove(note.id)` renders `onclick="window.remove(12)"`. Arguments are written as JSON.
    """

    def __init__(self, function: "JSFunction[...]", args: Iterable[object]) -> None:
        args = list(args)
        self.function = function
        # `window.` because inline handlers look names up on the element and its form first:
        # a bare `submit()` inside a <form> would call form.submit().
        self.code = f"window.{function.name}({', '.join(js_value(arg) for arg in args)})"
        self.uses: list[JSObject] = [function, *(arg for arg in args if isinstance(arg, JSObject))]
        """The definitions the page needs for this call: the function, and functions passed to it."""

    def __repr__(self) -> str:
        return f"JSCall({self.code!r})"


class UnsupportedSyntax(NotImplementedError):
    pass


def _function_scope_nodes(body: list[ast.stmt]) -> Iterator[ast.AST]:
    """Every node of a function body, without going into nested functions and comprehensions."""
    stack: list[ast.AST] = list(reversed(body))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda | ast.ListComp):
            stack += reversed(list(ast.iter_child_nodes(node)))


def local_names(definition: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    """The names a function assigns, minus its parameters and `global` names: they get one `let` at the top,
    which gives them Python's function scope instead of leaking into `window`."""
    params = {arg.arg for arg in definition.args.args}
    names: dict[str, None] = {}
    outer: set[str] = set()
    for node in _function_scope_nodes(definition.body):
        match node:
            case ast.Global(names=declared) | ast.Nonlocal(names=declared):
                outer.update(declared)
            case (
                ast.Assign(targets=[ast.Name(id=name)])
                | ast.AnnAssign(target=ast.Name(id=name))
                | ast.AugAssign(target=ast.Name(id=name))
                | ast.For(target=ast.Name(id=name))
            ):
                names[name] = None
            case _:
                pass
    return [name for name in names if name not in params and name not in outer]


def _template_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")


class Translator:
    def __init__(self, first_line: int = 1) -> None:
        self.first_line = first_line
        self.names: set[str] = set()
        """Every name the code reads: the candidates for other functions it needs on the page."""

    def unsupported(self, node: ast.AST, what: str | None = None) -> UnsupportedSyntax:
        line = getattr(node, "lineno", None)
        where = f"line {line + self.first_line - 1}: " if isinstance(line, int) else ""
        return UnsupportedSyntax(f"UnjustPython, {where}{what or type(node).__name__} is not supported")

    def js_name(self, name: str, node: ast.AST) -> str:
        if name in JS_RESERVED:
            raise self.unsupported(node, f"the name {name!r} (a reserved word in JavaScript)")
        return name

    def no_await(self, node: ast.AST) -> None:
        if any(isinstance(inner, ast.Await) for inner in ast.walk(node)):
            raise self.unsupported(node, "await inside a lambda or a comprehension")

    def operator[T](self, table: dict[type[T], str], op: T, node: ast.AST) -> str:
        if type(op) not in table:
            raise self.unsupported(node, f"the {type(op).__name__} operator")
        return table[type(op)]

    def block(self, statements: list[ast.stmt]) -> str:
        return " ".join(f"{code};" for statement in statements if (code := self.statement(statement)))

    def function(self, definition: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        args = definition.args
        if args.vararg or args.kwarg or args.kwonlyargs or args.posonlyargs or args.defaults:
            raise self.unsupported(definition, "*args, **kwargs, keyword-only and default parameters")
        body = definition.body
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            body = body[1:]  # docstring
        names = local_names(definition)
        for name in [definition.name, *(arg.arg for arg in args.args), *names]:
            self.js_name(name, definition)
        params = ", ".join(arg.arg for arg in args.args)
        declare = f"let {', '.join(names)}; " if names else ""
        keyword = "async function" if isinstance(definition, ast.AsyncFunctionDef) else "function"
        return f"{keyword} {definition.name}({params}) {{ {declare}{self.block(body)} }}"

    def statement(self, node: ast.stmt) -> str:
        match node:
            case ast.FunctionDef() | ast.AsyncFunctionDef():
                return self.function(node)
            case ast.Return(value=value):
                return f"return {self.expression(value)}" if value else "return"
            case ast.Expr(value=value):
                return self.expression(value)
            case ast.Assign(targets=[target], value=value) | ast.AnnAssign(target=target, value=ast.expr() as value):
                return f"{self.expression(target)} = {self.expression(value)}"
            case ast.AugAssign(target=target, op=op, value=value):
                return (
                    f"{self.expression(target)} {self.operator(BINARY_OPERATORS, op, node)}= {self.expression(value)}"
                )
            case ast.If(test=test, body=body, orelse=orelse):
                otherwise = f" else {{ {self.block(orelse)} }}" if orelse else ""
                return f"if ({self.expression(test)}) {{ {self.block(body)} }}{otherwise}"
            case ast.For(target=ast.Name(id=name), iter=ast.Call(func=ast.Name(id="range"), args=args), body=body):
                return f"for ({self.range_loop(name, args, node)}) {{ {self.block(body)} }}"
            case ast.For(target=ast.Name(id=name), iter=iterable, body=body, orelse=[]):
                return f"for ({name} of {self.expression(iterable)}) {{ {self.block(body)} }}"
            case ast.While(test=test, body=body, orelse=[]):
                return f"while ({self.expression(test)}) {{ {self.block(body)} }}"
            case ast.Break():
                return "break"
            case ast.Continue():
                return "continue"
            case ast.Pass() | ast.Global() | ast.Nonlocal() | ast.AnnAssign(value=None):
                return ""
            case _:
                raise self.unsupported(node)

    def expression(self, node: ast.expr) -> str:
        match node:
            case ast.Name(id=name) if name in PYTHON_ONLY:
                raise self.unsupported(node, f"{name} other than called with one argument (range only in a for loop)")
            case ast.Name(id=name):
                self.names.add(name)
                return self.js_name(name, node)
            case ast.Constant(value=bool(value)):
                return "true" if value else "false"
            case ast.Constant(value=None):
                return "null"
            case ast.Constant(value=int() | float() | str() as value):
                return json.dumps(value, ensure_ascii=False)
            case ast.JoinedStr(values=values):
                return "`" + "".join(self.template_part(part) for part in values) + "`"
            case ast.BinOp(left=left, op=op, right=right):
                operator = self.operator(BINARY_OPERATORS, op, node)
                return f"({self.expression(left)} {operator} {self.expression(right)})"
            case ast.UnaryOp(op=op, operand=operand):
                return f"({self.operator(UNARY_OPERATORS, op, node)}({self.expression(operand)}))"
            case ast.BoolOp(op=op, values=values):
                joiner = f" {self.operator(BOOLEAN_OPERATORS, op, node)} "
                return "(" + joiner.join(self.expression(value) for value in values) + ")"
            case ast.Compare(left=left, ops=[ast.Is() | ast.IsNot() as op], comparators=[ast.Constant(value=None)]):
                # `x is None` also catches JavaScript's undefined.
                return f"({self.expression(left)} {'==' if isinstance(op, ast.Is) else '!='} null)"
            case ast.Compare(left=left, ops=[op], comparators=[right]):
                operator = self.operator(COMPARISONS, op, node)
                return f"({self.expression(left)} {operator} {self.expression(right)})"
            case ast.IfExp(test=test, body=body, orelse=orelse):
                return f"({self.expression(test)} ? {self.expression(body)} : {self.expression(orelse)})"
            case ast.Call(func=ast.Name(id="len"), args=[value], keywords=[]):
                return f"{self.expression(value)}.length"
            case ast.Call(func=ast.Name(id="new"), args=[constructor, *args], keywords=[]):
                return f"new {self.expression(constructor)}({self.arguments(args)})"
            case ast.Call(func=ast.Name(id="print"), args=args, keywords=[]):
                return f"console.log({self.arguments(args)})"
            case ast.Call(func=ast.Name(id="int"), args=[value, base], keywords=[]):
                return f"parseInt({self.expression(value)}, {self.expression(base)})"
            case ast.Call(func=ast.Name(id=name), args=[value], keywords=[]) if name in BUILTINS:
                return f"{BUILTINS[name]}({self.expression(value)})"
            case ast.Call(func=func, args=args, keywords=[]):
                return f"{self.expression(func)}({self.arguments(args)})"
            case ast.Await(value=value):
                return f"(await {self.expression(value)})"
            case ast.Attribute(value=value, attr=attr):
                return f"{self.expression(value)}.{attr}"
            case ast.Subscript(slice=ast.UnaryOp(op=ast.USub()), ctx=ast.Store() | ast.Del()):
                raise self.unsupported(node, "assigning to a negative index")
            case ast.Subscript(
                value=value, slice=ast.UnaryOp(op=ast.USub(), operand=ast.Constant(value=int())) as index
            ):
                return f"{self.expression(value)}.at({self.expression(index)})"  # items[-1]
            case ast.Subscript(value=value, slice=index):
                return f"{self.expression(value)}[{self.expression(index)}]"
            case ast.List(elts=elements, ctx=ast.Load()) | ast.Tuple(elts=elements, ctx=ast.Load()):
                return f"[{self.arguments(elements)}]"
            case ast.Dict(keys=keys, values=values):
                return "{" + ", ".join(self.dict_item(k, v) for k, v in zip(keys, values, strict=True)) + "}"
            case ast.Lambda(args=args, body=body):
                if args.vararg or args.kwarg or args.kwonlyargs or args.posonlyargs or args.defaults:
                    raise self.unsupported(node, "lambda parameters other than plain names")
                self.no_await(node)
                params = ", ".join(self.js_name(arg.arg, node) for arg in args.args)
                return f"(({params}) => ({self.expression(body)}))"
            case ast.ListComp(elt=element, generators=[ast.comprehension(target=ast.Name(id=name), iter=it, ifs=ifs)]):
                self.no_await(node)
                self.js_name(name, node)
                code = self.expression(it)
                if ifs:
                    code += f".filter(({name}) => ({' && '.join(self.expression(test) for test in ifs)}))"
                return f"{code}.map(({name}) => ({self.expression(element)}))"
            case _:
                raise self.unsupported(node)

    def range_loop(self, name: str, args: list[ast.expr], node: ast.For) -> str:
        """`for i in range(...)` as a counting loop. The end is evaluated on every step, as JavaScript does."""
        if node.orelse:
            raise self.unsupported(node, "for/else")
        match args:
            case [stop]:
                start, step = "0", 1
            case [first, stop]:
                start, step = self.expression(first), 1
            case [first, stop, ast.Constant(value=int(step))] if step != 0:
                start = self.expression(first)
            case [first, stop, ast.UnaryOp(op=ast.USub(), operand=ast.Constant(value=int(negative)))] if negative:
                start, step = self.expression(first), -negative
            case _:
                raise self.unsupported(node, "range() with a step that isn't a number")
        compare = "<" if step > 0 else ">"
        return f"{name} = {start}; {name} {compare} {self.expression(stop)}; {name} += {step}"

    def arguments(self, nodes: list[ast.expr]) -> str:
        if any(isinstance(node, ast.Starred) for node in nodes):
            raise self.unsupported(nodes[0], "*unpacking")
        return ", ".join(self.expression(node) for node in nodes)

    def dict_item(self, key: ast.expr | None, value: ast.expr) -> str:
        if key is None:
            return f"...{self.expression(value)}"
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            return f"{json.dumps(key.value, ensure_ascii=False)}: {self.expression(value)}"
        return f"[{self.expression(key)}]: {self.expression(value)}"

    def template_part(self, node: ast.expr) -> str:
        match node:
            case ast.Constant(value=str(text)):
                return _template_text(text)
            case ast.FormattedValue(value=value, conversion=-1, format_spec=None):
                return "${" + self.expression(value) + "}"
            case _:
                raise self.unsupported(node, "f-string conversions and format specs")


def translate(source: str) -> str:
    """Translate Python statements to JavaScript."""
    translator = Translator()
    return translator.block(ast.parse(textwrap.dedent(source)).body)


class JSFunction[**P](JSObject):
    """A Python function translated to JavaScript, made by `@jsdef`.

    Use it as an attribute value (`onclick=save`) or call it with arguments for one
    (`onclick=remove(note.id)`). Calling it doesn't run it: it only runs in the browser.
    """

    def __init__(self, fn: Callable[P, object]) -> None:
        self.fn = fn
        self.name = check_js_name(fn.__name__)
        try:
            lines, first_line = inspect.getsourcelines(fn)
        except (OSError, TypeError) as e:
            raise ValueError(f"@jsdef needs the source of {fn.__name__}, in a file (not a REPL or a lambda)") from e
        match ast.parse(textwrap.dedent("".join(lines))).body:
            case [ast.FunctionDef() | ast.AsyncFunctionDef() as definition]:
                pass
            case _:
                raise ValueError(f"@jsdef: expected the source of one function, {fn.__name__}")
        translator = Translator(first_line)
        self.code = translator.function(definition)
        self.names = translator.names - {self.name}

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> Any:
        """A JSCall. Typed as Any so that calls inside other `@jsdef` functions type-check too."""
        if kwargs:
            raise TypeError("JavaScript functions take positional arguments only")
        return JSCall(self, args)

    def js_code(self) -> str:
        return self.code

    def js_dependencies(self) -> Iterator[JSObject]:
        # Looked up when the page renders, so a function can call one defined below it.
        scope: dict[str, object] = {**getattr(self.fn, "__globals__", {}), **inspect.getclosurevars(self.fn).nonlocals}
        for name in sorted(self.names):
            if isinstance(value := scope.get(name), JSObject):
                yield value

    def __repr__(self) -> str:
        return f"JSFunction({self.name!r})"


def jsdef[**P](fn: Callable[P, object]) -> JSFunction[P]:
    """Translate the decorated function to JavaScript, for use in rhtml attributes."""
    return JSFunction(fn)


def page_script(objects: Iterable[JSObject]) -> str:
    """The code for `objects` and everything they need, each once. Safe to put inside <script>."""
    defined: dict[str, JSObject] = {}
    ordered: list[JSObject] = []

    def visit(obj: JSObject) -> None:
        existing = defined.get(obj.name)
        if existing is obj:
            return
        if existing is not None:
            raise ValueError(f"two different JavaScript functions on one page are named {obj.name!r}")
        defined[obj.name] = obj
        for dependency in obj.js_dependencies():
            visit(dependency)
        ordered.append(obj)

    for obj in objects:
        visit(obj)
    code = "\n".join(obj.js_code() for obj in ordered)
    # `</script>` or `<!--` inside a string would end the script early. These escapes mean the same in JS.
    return code.replace("</", "<\\/").replace("<!--", "<\\!--")
