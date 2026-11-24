import unittest

import reugin.rhtml as h


class TagTest(unittest.TestCase):
    def test_children_sit_side_by_side(self) -> None:
        self.assertEqual(str(h.p("See ", h.a("docs", href="/docs"), ".")), '<p>See <a href="/docs">docs</a>.</p>')

    def test_lists_and_generators_are_flattened(self) -> None:
        tag = h.ul((h.li(n) for n in range(2)), [h.li("a"), [h.li("b")]], None, False)
        self.assertEqual(str(tag), "<ul><li>0</li><li>1</li><li>a</li><li>b</li></ul>")

    def test_escaping(self) -> None:
        tag = h.p("<script>", title='"quoted" & <tagged>')
        self.assertEqual(str(tag), '<p title="&quot;quoted&quot; &amp; &lt;tagged&gt;">&lt;script&gt;</p>')
        self.assertEqual(str(h.script("if (a < b) {}")), "<script>if (a < b) {}</script>")
        # Script and style text can't end its element early, whatever is in it.
        evil = "</script><script>alert(1)</script><!--"
        self.assertEqual(
            str(h.script(f"const s = {evil!r}")),
            "<script>const s = '<\\/script><script>alert(1)<\\/script><\\!--'</script>",
        )
        self.assertEqual(str(h.style("a{}</STYLE ><img>")), "<style>a{}<\\/STYLE ><img></style>")

    def test_attributes(self) -> None:
        tag = h.input(class_="field", data_id=5, disabled=True, hidden=False, placeholder=None)
        self.assertEqual(str(tag), '<input class="field" data-id="5" disabled>')

    def test_void_elements(self) -> None:
        self.assertEqual(str(h.img(src="a.png")), '<img src="a.png">')
        with self.assertRaises(ValueError):
            h.br("text")

    def test_fragment_and_raw(self) -> None:
        self.assertEqual(str(h.fragment(h.b("a"), "b")), "<b>a</b>b")
        self.assertEqual(str(h.div(h.raw("<hr>"))), "<div><hr></div>")

    def test_wrong_children(self) -> None:
        with self.assertRaises(TypeError):
            h.p(b"bytes")
        with self.assertRaises(TypeError):
            h.p(object())  # pyright: ignore[reportArgumentType]


class DocumentTest(unittest.TestCase):
    def test_document(self) -> None:
        card = h.div(h.stylesheet("/card.css"), "card")
        page = h.Document(card, card, title="Cards & co", lang="en", onload="start()", head=[h.meta(name="x")])
        self.assertEqual(
            str(page),
            '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>Cards &amp; co</title><meta name="x"><link rel="stylesheet" href="/card.css">'
            '</head><body onload="start()"><div>card</div><div>card</div></body></html>',
        )
