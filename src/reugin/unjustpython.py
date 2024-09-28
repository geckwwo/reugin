import inspect
import textwrap
import ast
import warnings

from .rhtml import IncludeString

class UnjustPythonTranslator:
    def transform_binop(self, node):
        operators = {
            ast.Add: '+',
            ast.Sub: '-',
            ast.Mult: '*',
            ast.Div: '/',
            ast.FloorDiv: '//',
            ast.Mod: '%',
            ast.Pow: '**'
        }
        return f"{self.transform(node.left)} {operators[type(node.op)]} {self.transform(node.right)}"
    
    def transform_compare(self, node):
        comparison_operators = {
            ast.Eq: '===',
            ast.NotEq: '!==',
            ast.Lt: '<',
            ast.LtE: '<=',
            ast.Gt: '>',
            ast.GtE: '>='
        }
        return f"{self.transform(node.left)} {comparison_operators[type(node.ops[0])]} {self.transform(node.comparators[0])}"

    def transform(self, node):
        if isinstance(node, ast.Module):
            return ';'.join(map(self.transform, node.body))
        elif isinstance(node, ast.FunctionDef):
            args = [arg.arg for arg in node.args.args]
            args_str = ', '.join(args)
            body = ';'.join(map(self.transform, node.body))
            return f"function {node.name}({args_str}) {{ {body} }}"
        elif isinstance(node, ast.ListComp):
            generator = node.generators[0]
            return f"{generator.iter.id}.map(function({generator.target.id}) {{ return {self.transform(node.elt)}; }})"
        elif isinstance(node, ast.Return):
            return f"return {self.transform(node.value)};"
        elif isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Num):
            return str(node.n)
        elif isinstance(node, ast.Str):
            return f"'{node.s}'"
        elif isinstance(node, ast.Constant):
            if isinstance(node.value, bool):
                return 'true' if node.value == True else "false"
            else:
                raise NotImplementedError(node)
        elif isinstance(node, ast.BinOp):
            return self.transform_binop(node)
        elif isinstance(node, ast.Compare):
            return self.transform_compare(node)
        elif isinstance(node, ast.Call):
            return f"{self.transform(node.func)}({', '.join(map(self.transform, node.args))})"
        elif isinstance(node, ast.Expr):
            return self.transform(node.value)
        elif isinstance(node, ast.Attribute):
            return f"{self.transform(node.value)}.{node.attr}"
        elif isinstance(node, ast.Assign):
            assert len(node.targets) == 1
            return f"{self.transform(node.targets[0])} = {self.transform(node.value)}"
        elif isinstance(node, ast.If):
            return f"if({self.transform(node.test)}) {{ {';'.join(map(self.transform, node.body))} }} else {{ { ";".join(map(self.transform, node.orelse)) } }}"
        elif isinstance(node, ast.Subscript):
            return f"{self.transform(node.value)}[{self.transform(node.slice)}]"
        elif isinstance(node, ast.For):
            assert isinstance(node.target, ast.Name)
            return f"for(const {node.target.id} of {self.transform(node.iter)}) {{ {';'.join(map(self.transform, node.body))} }}"
        else:
            raise NotImplementedError(f"UnjustPython: not implemented: {ast.dump(node)}")

    def generate_js_code(self, funcname, python_code):
        return self.transform(ast.parse(python_code))

class UnjustContext:
    def __init__(self):
        self.ctx = {}
        self.octx = ""
    
    def include_file(self, filename):
        self.octx += open(filename).read()
    def include_str(self, s):
        self.octx += s
    
    def jsdef(self, name=None):
        def inner(fn):
            nonlocal name

            if name is None:
                name = fn.__code__.co_name
            assert name not in self.ctx, "This function is already registered."
            self.ctx[name] = fn
            fn._reugin_unjustpython_jsname = name
            def inner2(*a, **kw):
                raise RuntimeError("This function is intended to be called from JavaScript context.")
            inner2._reugin_unjustpython_jsname = name
            return inner2
        return inner
    
    def build_script(self):
        b = self.octx + ""
        for fn_name, fn in self.ctx.items():
            src = inspect.getsource(fn)
            src = textwrap.dedent(src)
            b += UnjustPythonTranslator().generate_js_code(fn_name, src)
        return IncludeString("<script>/* Powered by Reugin's UnjustPython code translator -- this was automatically transpiled from Python source code to JavaScript -- Reugin Framework, UnjustPython transpiler (c) 2024 by geckonerd */"+ (b) +"</script>")

def js(function):
    warnings.warn(DeprecationWarning("Reugin's Python-to-JavaScript translation layer is deprecated. It is highly unstable and is not usable in 95% of cases and will be removed in the next major update. Use JavaScript or UnjustPython (this package)."))
    src = inspect.getsource(function)
    src = textwrap.dedent(src)
    return  UnjustPythonTranslator().generate_js_code(function.__code__.co_name, src)