import html
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import ClassVar, cast, override

from .misc import AttrValue, EmptyAttr, JSFunction, Property

__all__ = [
    "CSSInjection",
    "Child",
    "Document",
    "HeadInjection",
    "IncludeFile",
    "IncludeString",
    "Tag",
    "a",
    "abbr",
    "area",
    "article",
    "aside",
    "audio",
    "b",
    "base",
    "bind",
    "blockquote",
    "br",
    "button",
    "canvas",
    "caption",
    "code",
    "col",
    "colgroup",
    "datalist",
    "dd",
    "details",
    "dialog",
    "div",
    "dl",
    "dt",
    "em",
    "embed",
    "fieldset",
    "figcaption",
    "figure",
    "footer",
    "form",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hr",
    "i",
    "iframe",
    "img",
    "input",
    "kbd",
    "label",
    "legend",
    "li",
    "link",
    "main",
    "mark",
    "meta",
    "meter",
    "nav",
    "noscript",
    "ol",
    "optgroup",
    "option",
    "output",
    "p",
    "picture",
    "pre",
    "progress",
    "q",
    "s",
    "samp",
    "script",
    "section",
    "select",
    "small",
    "source",
    "span",
    "strong",
    "style",
    "sub",
    "summary",
    "sup",
    "table",
    "tbody",
    "td",
    "template",
    "textarea",
    "tfoot",
    "th",
    "thead",
    "time",
    "title",
    "tr",
    "track",
    "u",
    "ul",
    "var",
    "video",
    "wbr",
]


class HeadInjection:
    """A tag that belongs in the page's <head>, declared from anywhere in the body.

    `Document` collects them and keeps one per name, so a component can ask for its stylesheet
    however many times it appears.
    """

    def __init__(self, name: str, tag: "Tag") -> None:
        self.name = name
        self.tag = tag


type Child = Tag | HeadInjection | Property | str | int | float | None
"""What a tag can contain. None and booleans render as nothing, which helps with `cond and h.p(...)`."""


def attribute_name(name: str) -> str:
    """Python keyword arguments to HTML names: `class_` → `class`, `data_id` → `data-id`."""
    return name.rstrip("_").replace("_", "-")


def render_attribute(name: str, value: AttrValue) -> str:
    match value:
        case None | False:
            return ""
        case True | EmptyAttr():
            return name
        case JSFunction():
            text = f"{value.name}();"
        case _:
            text = str(value)
    return f'{name}="{html.escape(text, quote=True)}"'


class Tag:
    tag: ClassVar[str] = "NONE"
    void: ClassVar[bool] = False
    """Void elements (<img>, <input>, ...) have no content and no closing tag."""
    raw_text: ClassVar[bool] = False
    """<script> and <style> keep their text as is."""

    def __init__(self, *children: Child, **attributes: AttrValue) -> None:
        self.children: list[Child] = list(children)
        self.attributes: dict[str, AttrValue] = {attribute_name(k): v for k, v in attributes.items()}

    def render_attributes(self) -> str:
        pairs = [*self.attributes.items(), *((p.name, p.value) for p in self.children if isinstance(p, Property))]
        rendered = [text for name, value in pairs if (text := render_attribute(name, value))]
        return "".join(" " + text for text in rendered)

    def render_child(self, child: Child) -> str:
        match child:
            case Tag():
                return child.render()
            case HeadInjection() | Property() | None | bool():
                return ""
            case str() if self.raw_text:
                return child
            case _:
                return html.escape(str(child))

    def render_body(self, children: Iterable[Child]) -> str:
        return " ".join(text for child in children if (text := self.render_child(child)))

    def render(self) -> str:
        if self.void:
            if any(not isinstance(child, Property | HeadInjection) for child in self.children):
                raise ValueError(f"<{self.tag}> is a void element and can't have content")
            return f"<{self.tag}{self.render_attributes()}>"
        return f"<{self.tag}{self.render_attributes()}>{self.render_body(self.children)}</{self.tag}>"

    def __add__(self, other: Child) -> "Tag":
        """`tag + other` puts the two side by side, without a wrapping element."""
        if isinstance(self, bind):
            return bind(*self.children, other)
        return bind(self, other)

    def __str__(self) -> str:
        return self.render()


class bind(Tag):
    """Several children side by side, without a wrapping element."""

    @override
    def render(self) -> str:
        return self.render_body(self.children)


class Document(Tag):
    """A whole HTML page. Head injections found anywhere in the body end up in <head>."""

    tag = "html"

    def __init__(
        self,
        body: Child | list[Child] | tuple[Child, ...],
        head: Sequence[Child] | None = None,
        **attributes: AttrValue,
    ) -> None:
        super().__init__(**attributes)
        self.body: list[Child] = list(body) if isinstance(body, list | tuple) else [body]
        self.head: list[Child] = list(head or [])

    def head_append(self, tag: "Tag") -> "Document":
        self.head.append(tag)
        return self

    @override
    def __add__(self, other: Child) -> "Document":
        return Document([*self.body, other], self.head, **self.attributes)

    def fetch_injections(self, children: Iterable[Child]) -> dict[str, "Tag"]:
        injections: dict[str, Tag] = {}
        for child in children:
            if isinstance(child, HeadInjection):
                injections[child.name] = child.tag
            elif isinstance(child, Tag):
                injections.update(self.fetch_injections(child.children))
        return injections

    @override
    def render(self) -> str:
        injected = "".join(tag.render() for tag in self.fetch_injections(self.body).values())
        return (
            f"<!DOCTYPE html><html{self.render_attributes()}>"
            f'<head><meta charset="utf-8">{self.render_body(self.head)}{injected}</head>'
            f"<body>{self.render_body(self.body)}</body></html>"
        )


class IncludeFile(Tag):
    """The contents of a file, as raw HTML, read every time the page renders."""

    def __init__(self, filename: str | Path) -> None:
        super().__init__()
        self.contents = Path(filename)

    @override
    def render(self) -> str:
        return self.contents.read_text()


class IncludeString(Tag):
    """A string of raw HTML, not escaped."""

    def __init__(self, data: str) -> None:
        super().__init__()
        self.contents = data

    @override
    def render(self) -> str:
        return self.contents


def _tag(name: str, *, void: bool = False, raw_text: bool = False) -> type[Tag]:
    return cast(
        type[Tag], type(name, (Tag,), {"tag": name, "void": void, "raw_text": raw_text, "__module__": __name__})
    )


a = _tag("a")
abbr = _tag("abbr")
area = _tag("area", void=True)
article = _tag("article")
aside = _tag("aside")
audio = _tag("audio")
b = _tag("b")
base = _tag("base", void=True)
blockquote = _tag("blockquote")
br = _tag("br", void=True)
button = _tag("button")
canvas = _tag("canvas")
caption = _tag("caption")
code = _tag("code")
col = _tag("col", void=True)
colgroup = _tag("colgroup")
datalist = _tag("datalist")
dd = _tag("dd")
details = _tag("details")
dialog = _tag("dialog")
div = _tag("div")
dl = _tag("dl")
dt = _tag("dt")
em = _tag("em")
embed = _tag("embed", void=True)
fieldset = _tag("fieldset")
figcaption = _tag("figcaption")
figure = _tag("figure")
footer = _tag("footer")
form = _tag("form")
h1 = _tag("h1")
h2 = _tag("h2")
h3 = _tag("h3")
h4 = _tag("h4")
h5 = _tag("h5")
h6 = _tag("h6")
header = _tag("header")
hr = _tag("hr", void=True)
i = _tag("i")
iframe = _tag("iframe")
img = _tag("img", void=True)
input = _tag("input", void=True)
kbd = _tag("kbd")
label = _tag("label")
legend = _tag("legend")
li = _tag("li")
link = _tag("link", void=True)
main = _tag("main")
mark = _tag("mark")
meta = _tag("meta", void=True)
meter = _tag("meter")
nav = _tag("nav")
noscript = _tag("noscript")
ol = _tag("ol")
optgroup = _tag("optgroup")
option = _tag("option")
output = _tag("output")
p = _tag("p")
picture = _tag("picture")
pre = _tag("pre")
progress = _tag("progress")
q = _tag("q")
s = _tag("s")
samp = _tag("samp")
script = _tag("script", raw_text=True)
section = _tag("section")
select = _tag("select")
small = _tag("small")
source = _tag("source", void=True)
span = _tag("span")
strong = _tag("strong")
style = _tag("style", raw_text=True)
sub = _tag("sub")
summary = _tag("summary")
sup = _tag("sup")
table = _tag("table")
tbody = _tag("tbody")
td = _tag("td")
template = _tag("template")
textarea = _tag("textarea")
tfoot = _tag("tfoot")
th = _tag("th")
thead = _tag("thead")
time = _tag("time")
title = _tag("title")
tr = _tag("tr")
track = _tag("track", void=True)
u = _tag("u")
ul = _tag("ul")
var = _tag("var")
video = _tag("video")
wbr = _tag("wbr", void=True)


class CSSInjection(HeadInjection):
    """A stylesheet link for <head>, added once however many times it's used."""

    def __init__(self, name: str, css_link: str) -> None:
        super().__init__(name, link(href=css_link, rel="stylesheet"))
