"""rhtml: HTML written as Python calls.

h.div(h.p("Hi"), class_="card")  # <div class="card"><p>Hi</p></div>
"""

import html
from collections.abc import Iterable, Iterator
from itertools import chain
from typing import ClassVar, cast, override

from ..unjustpython import JSCall, JSFunction, JSObject, page_script

__all__ = [
    "AttrValue",
    "Child",
    "Document",
    "HeadInjection",
    "Tag",
    "a",
    "abbr",
    "area",
    "article",
    "aside",
    "audio",
    "b",
    "base",
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
    "fragment",
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
    "raw",
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
    "stylesheet",
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


type AttrValue = str | int | float | bool | JSFunction[...] | JSCall | None
"""None and False leave the attribute out; True renders it without a value. A JavaScript function
(see `reugin.jsdef`) renders as a call: `onclick=save` gives `onclick="window.save()"`."""


class HeadInjection:
    """A tag that belongs in the page's <head>, declared from anywhere in the body.

    `Document` keeps one per key, so a component can ask for its stylesheet however many times it appears.
    """

    def __init__(self, key: str, tag: "Tag") -> None:
        self.key = key
        self.tag = tag


type Leaf = Tag | HeadInjection | str | int | float | bool | None
type Child = Leaf | Iterable[Child]
"""What a tag can contain. Lists and generators are flattened; None and booleans render as nothing,
which helps with `done and h.p("Saved")`. Text is escaped."""


def flatten(children: Iterable[Child]) -> list[Leaf]:
    leaves: list[Leaf] = []
    for child in children:
        if child is None or isinstance(child, Tag | HeadInjection | str | int | float):
            leaves.append(child)
        elif isinstance(child, bytes | bytearray):
            raise TypeError("rhtml takes text, not bytes: decode it first")
        else:
            try:
                nested = list(child)
            except TypeError:
                raise TypeError(f"a {type(child).__name__} can't go inside a tag") from None
            leaves += flatten(nested)
    return leaves


def attribute_name(name: str) -> str:
    """Python keyword arguments to HTML names: `class_` → `class`, `data_id` → `data-id`."""
    return name.rstrip("_").replace("_", "-")


def render_attribute(name: str, value: AttrValue) -> str:
    match value:
        case None | False:
            return ""
        case True:
            return name
        case JSFunction():
            text = f"window.{value.name}()"  # see JSCall: a bare name could hit the element's own method
        case JSCall():
            text = value.code
        case _:
            text = str(value)
    return f'{name}="{html.escape(text, quote=True)}"'


def js_references(values: Iterable[AttrValue]) -> Iterator[JSObject]:
    for value in values:
        if isinstance(value, JSFunction):
            yield value
        elif isinstance(value, JSCall):
            yield from value.uses


class Tag:
    tag: ClassVar[str] = ""
    void: ClassVar[bool] = False
    """Void elements (<img>, <input>, ...) have no content and no closing tag."""
    raw_text: ClassVar[bool] = False
    """<script> and <style> keep their text unescaped, apart from `</` and `<!--`, which would end them."""

    def __init__(self, *children: Child, **attributes: AttrValue) -> None:
        self.children = flatten(children)
        self.attributes = {attribute_name(name): value for name, value in attributes.items()}
        if self.void and any(child is not None and not isinstance(child, HeadInjection) for child in self.children):
            raise ValueError(f"<{self.tag}> is a void element and can't have content")

    def render_attributes(self) -> str:
        return "".join(" " + text for name, value in self.attributes.items() if (text := render_attribute(name, value)))

    def render_child(self, child: Leaf) -> str:
        match child:
            case Tag():
                return child.render()
            case HeadInjection() | None | bool():
                return ""
            case str() if self.raw_text:
                # Script and style text isn't HTML-escaped, but it mustn't end its element early.
                return child.replace("</", "<\\/").replace("<!--", "<\\!--")
            case _:
                return html.escape(str(child))

    def render_children(self) -> str:
        return "".join(self.render_child(child) for child in self.children)

    def render(self) -> str:
        if self.void:
            return f"<{self.tag}{self.render_attributes()}>"
        return f"<{self.tag}{self.render_attributes()}>{self.render_children()}</{self.tag}>"

    def walk(self) -> Iterator["Tag | HeadInjection"]:
        """This tag and everything inside it, head injections included."""
        yield self
        for child in self.children:
            if isinstance(child, Tag):
                yield from child.walk()
            elif isinstance(child, HeadInjection):
                yield child
                yield from child.tag.walk()

    def __str__(self) -> str:
        return self.render()


class fragment(Tag):
    """Several children side by side, without a wrapping element."""

    @override
    def render(self) -> str:
        return self.render_children()


class raw(Tag):
    """HTML as it is, not escaped. Only for markup you trust."""

    def __init__(self, markup: str) -> None:
        super().__init__()
        self.markup = markup

    @override
    def render(self) -> str:
        return self.markup


class Document(Tag):
    """A whole HTML page: `h.Document(h.h1("Notes"), ..., title="Notes", lang="en")`.

    Head injections from anywhere in the page go into <head>, and so does one <script> with every
    JavaScript function the page's attributes use. Event attributes such as `onload=` go on <body>;
    the others on <html>.
    """

    tag = "html"

    def __init__(
        self, *body: Child, head: Iterable[Child] = (), title: str | None = None, **attributes: AttrValue
    ) -> None:
        super().__init__(*body, **{name: value for name, value in attributes.items() if not name.startswith("on")})
        self.body_attributes = {name: value for name, value in attributes.items() if name.startswith("on")}
        self.head = flatten(head)
        self.title = title

    @override
    def render(self) -> str:
        injections: dict[str, Tag] = {}
        scripts: list[JSObject] = list(js_references(self.body_attributes.values()))
        head_tags = [tag.walk() for tag in self.head if isinstance(tag, Tag)]
        for node in chain(self.walk(), *head_tags):
            if isinstance(node, HeadInjection):
                injections.setdefault(node.key, node.tag)
            else:
                scripts += js_references(node.attributes.values())
        code = page_script(scripts)
        body_attributes = "".join(
            " " + text for name, value in self.body_attributes.items() if (text := render_attribute(name, value))
        )
        return "".join(
            [
                f"<!DOCTYPE html><html{self.render_attributes()}><head>",
                '<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">',
                f"<title>{html.escape(self.title)}</title>" if self.title is not None else "",
                "".join(self.render_child(child) for child in self.head),
                "".join(tag.render() for tag in injections.values()),
                f"<script>{code}</script>" if code else "",
                f"</head><body{body_attributes}>{self.render_children()}</body></html>",
            ]
        )


def stylesheet(href: str) -> HeadInjection:
    """A <link rel="stylesheet"> for <head>, added once however many times it's used."""
    return HeadInjection(href, link(rel="stylesheet", href=href))


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
