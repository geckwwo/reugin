"""UnjustPython: small Python functions translated to JavaScript, for event handlers in rhtml pages.

    ctx = UnjustContext()

    @ctx.jsdef()
    def greet():
        alert("Hello!")

    page = h.Document([h.button("Hi", onclick=greet), ctx.build_script()])

It covers a small, readable subset of Python: calls, attributes, arithmetic and comparisons,
`if`/`for`/`while`, list literals, list comprehensions and assignments. Anything else raises
NotImplementedError, naming the construct, so nothing is translated silently wrong.
"""

import ast
import inspect
import json
import textwrap
from collections.abc import Callable
from pathlib import Path

from .rhtml import IncludeString, JSFunction

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
}
UNARY_OPERATORS: dict[type[ast.unaryop], str] = {ast.Not: "!", ast.USub: "-", ast.UAdd: "+"}
BOOLEAN_OPERATORS: dict[type[ast.boolop], str] = {ast.And: "&&", ast.Or: "||"}


class UnjustPythonTranslator:
    def block(self, statements: list[ast.stmt]) -> str:
        return ";".join(self.transform(s) for s in statements)

    def operator[T](self, table: dict[type[T], str], op: T) -> str:
        if type(op) not in table:
            raise NotImplementedError(f"UnjustPython: operator {type(op).__name__} is not supported")
        return table[type(op)]

    def transform(self, node: ast.AST) -> str:
        match node:
            case ast.Module(body=body):
                return self.block(body)
            case ast.FunctionDef(name=name, args=args, body=body):
                params = ", ".join(arg.arg for arg in args.args)
                return f"function {name}({params}) {{ {self.block(body)} }}"
            case ast.Return(value=value):
                return f"return {self.transform(value)};" if value else "return;"
            case ast.Expr(value=value):
                return self.transform(value)
            case ast.Assign(targets=[target], value=value):
                return f"{self.transform(target)} = {self.transform(value)}"
            case ast.AugAssign(target=target, op=op, value=value):
                return f"{self.transform(target)} {self.operator(BINARY_OPERATORS, op)}= {self.transform(value)}"
            case ast.If(test=test, body=body, orelse=orelse):
                otherwise = f" else {{ {self.block(orelse)} }}" if orelse else ""
                return f"if ({self.transform(test)}) {{ {self.block(body)} }}{otherwise}"
            case ast.For(target=ast.Name(id=name), iter=iterable, body=body, orelse=[]):
                return f"for (const {name} of {self.transform(iterable)}) {{ {self.block(body)} }}"
            case ast.While(test=test, body=body, orelse=[]):
                return f"while ({self.transform(test)}) {{ {self.block(body)} }}"
            case ast.Pass():
                return ""
            case ast.Name(id=name):
                return name
            case ast.Constant(value=bool(value)):
                return "true" if value else "false"
            case ast.Constant(value=None):
                return "null"
            case ast.Constant(value=int() | float() | str() as value):
                return json.dumps(value)
            case ast.BinOp(left=left, op=op, right=right):
                return f"({self.transform(left)} {self.operator(BINARY_OPERATORS, op)} {self.transform(right)})"
            case ast.UnaryOp(op=op, operand=operand):
                return f"{self.operator(UNARY_OPERATORS, op)}({self.transform(operand)})"
            case ast.BoolOp(op=op, values=values):
                joiner = f" {self.operator(BOOLEAN_OPERATORS, op)} "
                return "(" + joiner.join(self.transform(v) for v in values) + ")"
            case ast.Compare(left=left, ops=[op], comparators=[right]):
                return f"({self.transform(left)} {self.operator(COMPARISONS, op)} {self.transform(right)})"
            case ast.Call(func=func, args=args, keywords=[]):
                return f"{self.transform(func)}({', '.join(self.transform(a) for a in args)})"
            case ast.Attribute(value=value, attr=attr):
                return f"{self.transform(value)}.{attr}"
            case ast.Subscript(value=value, slice=index):
                return f"{self.transform(value)}[{self.transform(index)}]"
            case ast.List(elts=elements):
                return f"[{', '.join(self.transform(e) for e in elements)}]"
            case ast.ListComp(elt=element, generators=[ast.comprehension(target=ast.Name(id=name), iter=it, ifs=[])]):
                return f"{self.transform(it)}.map(function({name}) {{ return {self.transform(element)}; }})"
            case _:
                raise NotImplementedError(f"UnjustPython: not supported: {ast.dump(node)}")

    def generate_js_code(self, python_code: str) -> str:
        return self.transform(ast.parse(python_code))


class UnjustContext:
    """Collects translated functions and plain JavaScript, and renders them as one <script>."""

    def __init__(self) -> None:
        self.ctx: dict[str, Callable[..., object]] = {}
        self.octx = ""

    def include_file(self, filename: str | Path) -> None:
        self.octx += Path(filename).read_text()

    def include_str(self, s: str) -> None:
        self.octx += s

    def jsdef(self, name: str | None = None) -> Callable[[Callable[..., object]], JSFunction]:
        """Translate the decorated function to JavaScript. Use the result as an rhtml attribute value."""

        def register(fn: Callable[..., object]) -> JSFunction:
            js_name = name or fn.__name__
            if js_name in self.ctx:
                raise ValueError(f"a JavaScript function named {js_name!r} is already registered")
            self.ctx[js_name] = fn
            return JSFunction(js_name)

        return register

    def build_script(self) -> IncludeString:
        code = self.octx
        translator = UnjustPythonTranslator()
        for fn_name, fn in self.ctx.items():
            tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
            match tree.body:
                case [ast.FunctionDef() as definition]:
                    definition.name = fn_name
                    definition.decorator_list = []
                    code += translator.transform(definition) + ";"
                case _:
                    raise ValueError(f"{fn_name}: expected the source of one function")
        return IncludeString(f"<script>/* Autogenerated */{code}</script>")
