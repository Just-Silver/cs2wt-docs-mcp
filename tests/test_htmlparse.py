import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cs2wt.htmlparse import extract_links, extract_meta, page_url

FULL = """
<html><body>
<h1 id="firstHeading" class="firstHeading" lang="en">Assault</h1>
<div id="mw-content-text"><p>body</p></div>
<a href="/w/index.php?title=Assault&amp;oldid=218612">Permanent link</a>
<li>This page was last modified on 5 September 2018, at 02:16.</li>
</body></html>
"""


class ExtractMetaTest(unittest.TestCase):
    def test_full(self):
        meta = extract_meta(FULL)
        self.assertEqual(meta["title"], "Assault")
        self.assertEqual(meta["revid"], 218612)
        self.assertEqual(meta["timestamp"], "2018-09-05T02:16:00")

    def test_missing_revid_and_timestamp(self):
        meta = extract_meta("<h1 id='firstHeading'>Foo</h1>")
        self.assertEqual(meta["title"], "Foo")
        self.assertIsNone(meta["revid"])
        self.assertEqual(meta["timestamp"], "")

    def test_entities_decoded(self):
        meta = extract_meta("<h1 id='firstHeading'>A &amp; B</h1>")
        self.assertEqual(meta["title"], "A & B")

    def test_page_url(self):
        self.assertEqual(
            page_url("Path corner"),
            "https://developer.valvesoftware.com/wiki/Path_corner",
        )


LINKS = """
<div id="mw-content-text">
<a href="/wiki/Path_corner">Path corner</a>
<a href="/wiki/Path_corner">dup</a>
<a href="/wiki/Ai_goal_assault#top">fragment</a>
<a href="/wiki/Special:Search">special</a>
<a href="/wiki/File:Logo.png">file</a>
<a href="/wiki/Template:Note">template</a>
<a href="/w/index.php?title=X">api path</a>
<a href="https://example.com/wiki/External">external</a>
<a href="//example.com/wiki/Proto">protocol-relative</a>
</div>
"""


class ExtractLinksTest(unittest.TestCase):
    def test_filters_and_normalizes(self):
        self.assertEqual(
            extract_links(LINKS),
            ["Path corner", "Ai goal assault"],
        )


if __name__ == "__main__":
    unittest.main()


from cs2wt.htmlparse import html_to_markdown

PAGE = """
<html><body>
<div id="toc"><p>toc junk</p></div>
<div id="mw-content-text" class="mw-body-content">
  <h2><span class="mw-headline">Alpha</span></h2>
  <p>Hello <b>bold</b> and <i>italic</i> with <code>x</code>.</p>
  <ul><li>one</li><li>two</li></ul>
  <pre>code line</pre>
  <a href="/wiki/Path_corner">Path corner</a>
  <a href="https://example.com">Ext</a>
  <span class="mw-editsection">edit</span>
  <table><tr><td>drop me</td></tr></table>
  <script>var x = 1;</script>
</div>
</body></html>
"""


class HtmlToMarkdownTest(unittest.TestCase):
    def test_conversion(self):
        md = html_to_markdown(PAGE)
        self.assertIn("## Alpha", md)
        self.assertIn("Hello **bold** and *italic* with `x`.", md)
        self.assertIn("- one", md)
        self.assertIn("- two", md)
        self.assertIn("```", md)
        self.assertIn("code line", md)
        self.assertIn("[Path corner](https://developer.valvesoftware.com/wiki/Path_corner)", md)
        self.assertIn("[Ext](https://example.com)", md)
        # dropped elements
        self.assertNotIn("toc junk", md)
        self.assertNotIn("edit", md)
        self.assertNotIn("drop me", md)
        self.assertNotIn("var x", md)

    def test_falls_back_to_body(self):
        md = html_to_markdown("<html><body><p>plain</p></body></html>")
        self.assertEqual(md, "plain")

    def test_void_element_with_drop_class_does_not_swallow(self):
        # A void element has no end tag; matching a drop class must not swallow
        # the rest of the document.
        md = html_to_markdown(
            '<div id="mw-content-text"><img class="metadata" src="x.png">'
            "<p>keep me</p></div>"
        )
        self.assertIn("keep me", md)

    def test_self_closing_void_inside_dropped_region(self):
        # A self-closing void inside a dropped region must not end drop mode.
        md = html_to_markdown(
            '<div id="mw-content-text">'
            '<div class="navbox">secret<br/>leaked</div><p>body</p></div>'
        )
        self.assertNotIn("secret", md)
        self.assertNotIn("leaked", md)
        self.assertIn("body", md)


if __name__ == "__main__":
    unittest.main()