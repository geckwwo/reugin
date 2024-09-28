from .misc import *
import html

class Tag:
    tag = "NONE"

    def __init__(self, *body, **attributes):
        self.rdbody = body
        self.rdattributes = attributes
        for attr, value in attributes.items():
            setattr(self, attr, value)
    
    def render_attribute(self, attr):
        if isinstance(attr, Property):
            attr = (attr.name, attr.value)
        name = attr[0]
        value = attr[1]
        if isinstance(value, (str, int, float)):
            value = str(value)
        elif isinstance(value, EmptyAttr):
            return f'{name}'
        elif hasattr(value, "_reugin_feature_rpc_call"):
            raise NotImplementedError("RPC calls as attribute callbacks are not implemented yet")
            value = f'alert(&quot;RPC Calls are WIP&quot;)'
        elif hasattr(value, "_reugin_unjustpython_jsname"):
            value = value._reugin_unjustpython_jsname + "();"
        else:
            raise NotImplementedError(f"Cannot serialize attribute of type {type(value)}")
        
        return f'{name}="{str(value).replace("\"","&quot;")}"'

    def render_body(self, body):
        def render_item(item):
            if isinstance(item, Tag):
                return item.render()
            elif isinstance(item, (HeadInjection, Property)):
                return ""
            else:
                return html.escape(str(item))
        return ' '.join(map(render_item, body))

    def render(self):
        #print(self.tag, list(self.rdattributes.items()) + [x for x in self.rdbody if isinstance(x, Property)])
        return f"<{self.tag}{(' ' + ' '.join(map(lambda x: self.render_attribute(x), list(self.rdattributes.items()) + [x for x in self.rdbody if isinstance(x, Property)])))}>{self.render_body(self.rdbody)}</{self.tag}>"

    def __add__(self, other):
        assert isinstance(other, (Tag, HeadInjection, Property, str)), f"Expected Tag, got {other}"
        if isinstance(self, bind):
            return bind(*self.rdbody, other)
        return bind(self, other)

class Document(Tag):
    def __init__(self, body, head=None):
        self.body = body
        self.head = head or []
    
    def head_append(self, tag):
        assert isinstance(tag, Tag), f"Expected Tag, got {tag}"
        self.head.append(tag)
        return self

    def __add__(self, other):
        assert isinstance(other, (Tag, HeadInjection, Property, str))
        return Document(self.body + [other], self.head)
    
    def fetch_injections(self, body):
        injections = {}
        for tag in body:
            if isinstance(tag, HeadInjection):
                injections[tag.name] = tag.tag
                continue
            if not isinstance(tag, Tag):
                continue
            injections.update(self.fetch_injections(tag.rdbody))
            injections.update({x.name: x.tag for x in tag.rdbody if isinstance(x, HeadInjection)})
        return injections

    def render(self):
        return f"<!DOCTYPE html><head>{self.render_body(self.head)}{"".join(map(lambda x: x.render(), self.fetch_injections(self.body).values()))}</head><body>{self.render_body(self.body)}</body>"
    

class HeadInjection:
    def __init__(self, name, tag):
        self.name = name
        self.tag = tag
class CSSInjection(HeadInjection):
    def __init__(self, name, css_link):
        self.name = name
        self.tag = link(href=css_link, rel="stylesheet")

class bind(Tag):
    def render(self):
        return self.render_body(self.rdbody)

class script(Tag):
    tag = "script"

class table(Tag):
    tag = "table"
class tr(Tag):
    tag = "tr"
class th(Tag):
    tag = "th"
class td(Tag):
    tag = "td"


class div(Tag):
    tag = "div"
class p(Tag):
    tag = "p"
class button(Tag):
    tag = "button"

class title(Tag):
    tag = "title"
class meta(Tag):
    tag = "meta"
class link(Tag):
    tag = "link"

class a(Tag):
    tag = "a"
class img(Tag):
    tag = "img"
class iframe(Tag):
    tag = "iframe"
class input(Tag):
    tag = "input"
class b(Tag):
    tag = "b"

class IncludeFile(Tag):
    def __init__(self, filename):
        self.contents = filename
        self.rdbody = []
    def render(self):
        return open(self.contents).read()
    
class IncludeString(Tag):
    def __init__(self, data):
        self.contents = data
        self.rdbody = []
    def render(self):
        return self.contents