from typing import Never

__all__ = ["AttrValue", "EmptyAttr", "JSFunction", "PClass", "Property"]


class EmptyAttr:
    """An attribute without a value, such as `disabled`. Passing `True` does the same."""


class JSFunction:
    """A JavaScript function, by name. As an attribute value it renders as a call: `onclick="name();"`.

    `UnjustContext.jsdef` returns one for every function it translates.
    """

    def __init__(self, name: str) -> None:
        self.name = name

    def __call__(self, *args: object, **kwargs: object) -> Never:
        raise RuntimeError(f"{self.name}() runs in the browser, not in Python")

    def __repr__(self) -> str:
        return f"JSFunction({self.name!r})"


type AttrValue = str | int | float | bool | EmptyAttr | JSFunction | None
"""None and False leave the attribute out; True and EmptyAttr() render it without a value."""


class Property:
    """An attribute given as a child, so it can sit next to the content: `h.div(PClass("card"), ...)`."""

    def __init__(self, name: str, value: AttrValue) -> None:
        self.name = name
        self.value = value


class PClass(Property):
    def __init__(self, value: str) -> None:
        super().__init__("class", value)
