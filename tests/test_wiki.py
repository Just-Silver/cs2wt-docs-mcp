import sys
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cs2wt.wiki import HtmlClient

BASE = "https://developer.valvesoftware.com"


def page_html(title, links=(), revid=1):
    anchors = "".join(f'<a href="/wiki/{link}">{link}</a>' for link in links)
    return (
        f'<h1 id="firstHeading">{title}</h1>'
        f'<div id="mw-content-text"><p>{title} body</p>{anchors}</div>'
        f'<a href="/w/index.php?title={title}&oldid={revid}">link</a>'
    ).encode("utf-8")


class FakeSession:
    def __init__(self, pages):
        self.pages = pages
        self.requested = []

    def get(self, url):
        self.requested.append(url)
        if url not in self.pages:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        return self.pages[url]


class HtmlClientTest(unittest.TestCase):
    def test_fetch_page_parses_meta(self):
        client = HtmlClient(FakeSession({f"{BASE}/wiki/A": page_html("A", revid=7)}))
        page = client.fetch_page("A")
        self.assertEqual(page.title, "A")
        self.assertEqual(page.revid, 7)
        self.assertIn("A body", page.html)

    def test_fetch_page_404_returns_none(self):
        client = HtmlClient(FakeSession({}))
        self.assertIsNone(client.fetch_page("Missing"))

    def test_iter_pages_bfs_filters_prefix_and_dedups(self):
        pages = {
            f"{BASE}/wiki/Root": page_html("Root", links=["Root/Child_One", "Root/Child_Two", "Outside"]),
            f"{BASE}/wiki/Root/Child_One": page_html("Root/Child One", links=["Root/Leaf"]),
            f"{BASE}/wiki/Root/Child_Two": page_html("Root/Child Two", links=["Root/Child_One"]),
            f"{BASE}/wiki/Root/Leaf": page_html("Root/Leaf"),
            f"{BASE}/wiki/Outside": page_html("Outside"),
        }
        client = HtmlClient(FakeSession(pages))
        titles = [page.title for page in client.iter_pages("Root")]
        self.assertEqual(titles, ["Root", "Root/Child One", "Root/Child Two", "Root/Leaf"])

    def test_iter_pages_reuses_known_cache(self):
        session = FakeSession({f"{BASE}/wiki/Root": page_html("Root")})
        client = HtmlClient(session)
        known = {}
        list(client.iter_pages("Root", known=known))
        self.assertIn("Root", known)
        # 第二次复用缓存，不再发请求
        before = len(session.requested)
        list(client.iter_pages("Root", known=known))
        self.assertEqual(len(session.requested), before)


if __name__ == "__main__":
    unittest.main()