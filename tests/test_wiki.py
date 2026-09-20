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
    def __init__(self, pages, errors=()):
        self.pages = pages
        self.errors = set(errors)
        self.requested = []

    def get(self, url):
        self.requested.append(url)
        if url in self.errors:
            raise RuntimeError(f"boom: {url}")
        if url not in self.pages:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        return self.pages[url]


class FlakySession:
    """Session that fails a fixed number of times before serving the page."""

    def __init__(self, response, failures=0, code=500):
        self.response = response
        self.remaining = failures
        self.code = code
        self.calls = 0

    def get(self, url):
        self.calls += 1
        if self.remaining > 0:
            self.remaining -= 1
            raise urllib.error.HTTPError(url, self.code, "error", {}, None)
        return self.response


class FetchRetryTest(unittest.TestCase):
    def test_fetch_page_retries_transient_failure_then_succeeds(self):
        session = FlakySession(page_html("A", revid=7), failures=1)
        client = HtmlClient(session, retries=2, retry_delay=0)
        page = client.fetch_page("A")
        self.assertIsNotNone(page)
        self.assertEqual(page.revid, 7)
        self.assertEqual(session.calls, 2)

    def test_fetch_page_raises_after_all_retries(self):
        session = FlakySession(page_html("A"), failures=99)
        client = HtmlClient(session, retries=3, retry_delay=0)
        with self.assertRaises(urllib.error.HTTPError):
            client.fetch_page("A")
        self.assertEqual(session.calls, 3)

    def test_fetch_page_404_is_not_retried(self):
        session = FlakySession(page_html("A"), failures=99, code=404)
        client = HtmlClient(session, retries=3, retry_delay=0)
        self.assertIsNone(client.fetch_page("A"))
        self.assertEqual(session.calls, 1)


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

    def test_iter_pages_dedups_same_actual_title(self):
        # Two queued link titles ("A", "B") redirect to the same actual page
        # ("T"); the page must be yielded once even though both were queued.
        pages = {
            f"{BASE}/wiki/T": page_html("T"),
            f"{BASE}/wiki/A": page_html("T"),
            f"{BASE}/wiki/B": page_html("T"),
        }
        client = HtmlClient(FakeSession(pages))
        titles = [page.title for page in client.iter_pages("T", seeds=["A", "B"])]
        self.assertEqual(titles.count("T"), 1)
        self.assertEqual(titles, ["T"])

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

    def test_iter_pages_skips_failed_page_and_records_it(self):
        pages = {
            f"{BASE}/wiki/Root": page_html("Root", links=["Root/Bad", "Root/Good"]),
            f"{BASE}/wiki/Root/Bad": page_html("Root/Bad", links=["Root/Deep"]),
            f"{BASE}/wiki/Root/Good": page_html("Root/Good"),
            f"{BASE}/wiki/Root/Deep": page_html("Root/Deep"),
        }
        session = FakeSession(pages, errors={f"{BASE}/wiki/Root/Bad"})
        client = HtmlClient(session, retry_delay=0)
        failed = []
        titles = [p.title for p in client.iter_pages("Root", failed=failed)]

        self.assertIn("Root", titles)
        self.assertIn("Root/Good", titles)
        self.assertNotIn("Root/Bad", titles)
        # 失败页的链接不会被继续遍历
        self.assertNotIn("Root/Deep", titles)
        self.assertEqual(failed, ["Root/Bad"])


if __name__ == "__main__":
    unittest.main()