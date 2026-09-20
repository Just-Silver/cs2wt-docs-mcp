import sys
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cs2wt.wiki import HtmlClient, PageContent

BASE = "https://developer.valvesoftware.com"


def page_html(title, links=(), revid=1):
    anchors = "".join(f'<a href="/wiki/{link}">{link}</a>' for link in links)
    return (
        f'<h1 id="firstHeading">{title}</h1>'
        f'<div id="mw-content-text"><p>{title} body</p>{anchors}</div>'
        f'<a href="/w/index.php?title={title}&oldid={revid}">link</a>'
    ).encode("utf-8")


def prefix_html(*links):
    """Build a fake Special:PrefixIndex page linking to ``links``."""
    anchors = "".join(f'<a href="/wiki/{link}">{link}</a>' for link in links)
    return (
        '<h1 id="firstHeading">Special:PrefixIndex</h1>'
        f'<div id="mw-content-text">{anchors}</div>'
    ).encode("utf-8")


def redirect_html(title, revid=3):
    """Build a rendered redirect page (contains ``mw-redirectedfrom``)."""
    return (
        f'<h1 id="firstHeading">{title}</h1>'
        '<span class="mw-redirectedfrom">(Redirected from X)</span>'
        f'<div id="mw-content-text"><p>{title} body</p></div>'
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


class UrLErrorSession:
    """Session that raises ``URLError`` a fixed number of times, then serves."""

    def __init__(self, response, failures=0):
        self.response = response
        self.remaining = failures
        self.calls = 0

    def get(self, url):
        self.calls += 1
        if self.remaining > 0:
            self.remaining -= 1
            raise urllib.error.URLError("boom")
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

    def test_fetch_page_title_is_requested_title_not_h1(self):
        html = (
            '<h1 id="firstHeading">Different Display Title</h1>'
            '<div id="mw-content-text"><p>body</p></div>'
            '<a href="/w/index.php?title=X&oldid=7">link</a>'
        ).encode("utf-8")
        client = HtmlClient(FakeSession({f"{BASE}/wiki/URL_Title": html}))
        page = client.fetch_page("URL Title")
        self.assertEqual(page.title, "URL Title")
        self.assertEqual(page.revid, 7)

    def test_fetch_page_marks_redirect(self):
        client = HtmlClient(
            FakeSession({f"{BASE}/wiki/Root/Redirect": redirect_html("Root/Redirect")})
        )
        page = client.fetch_page("Root/Redirect")
        self.assertTrue(page.is_redirect)

    def test_fetch_page_non_redirect_flag_is_false(self):
        client = HtmlClient(FakeSession({f"{BASE}/wiki/Root/A": page_html("Root/A")}))
        page = client.fetch_page("Root/A")
        self.assertFalse(page.is_redirect)

    def test_fetch_page_404_returns_none(self):
        client = HtmlClient(FakeSession({}))
        self.assertIsNone(client.fetch_page("Missing"))

    def test_list_titles_filters_prefix_dedups_and_keeps_order(self):
        session = FakeSession({
            f"{BASE}/wiki/Special:PrefixIndex/Root": prefix_html(
                "Root/B", "Outside/X", "Root/A", "Root/B", "Root/C"
            )
        })
        client = HtmlClient(session)
        self.assertEqual(client.list_titles("Root"), ["Root/B", "Root/A", "Root/C"])
        self.assertEqual(session.requested[0], f"{BASE}/wiki/Special:PrefixIndex/Root")

    def test_list_titles_quotes_prefix_in_url(self):
        session = FakeSession({
            f"{BASE}/wiki/Special:PrefixIndex/Root/Sub_Page": prefix_html("Root/Sub Page/A")
        })
        client = HtmlClient(session)
        self.assertEqual(client.list_titles("Root/Sub Page"), ["Root/Sub Page/A"])
        self.assertEqual(
            session.requested[0], f"{BASE}/wiki/Special:PrefixIndex/Root/Sub_Page"
        )

    def test_list_titles_retries_transient_failure_then_succeeds(self):
        session = UrLErrorSession(prefix_html("Root/A"), failures=1)
        client = HtmlClient(session, retries=2, retry_delay=0)
        self.assertEqual(client.list_titles("Root"), ["Root/A"])
        self.assertEqual(session.calls, 2)

    def test_list_titles_raises_when_all_attempts_fail(self):
        session = UrLErrorSession(prefix_html("Root/A"), failures=99)
        client = HtmlClient(session, retries=3, retry_delay=0)
        with self.assertRaises(urllib.error.URLError):
            client.list_titles("Root")
        self.assertEqual(session.calls, 3)

    def test_list_titles_raises_on_404_instead_of_empty_list(self):
        client = HtmlClient(FakeSession({}))
        with self.assertRaises(RuntimeError):
            client.list_titles("Root")

    def test_iter_pages_skips_404_and_redirect(self):
        pages = {
            f"{BASE}/wiki/Special:PrefixIndex/Root": prefix_html(
                "Root/A", "Root/Missing", "Root/Redirect", "Root/B"
            ),
            f"{BASE}/wiki/Root/A": page_html("Root/A"),
            f"{BASE}/wiki/Root/Redirect": redirect_html("Root/Redirect"),
            f"{BASE}/wiki/Root/B": page_html("Root/B"),
        }
        client = HtmlClient(FakeSession(pages))
        titles = [p.title for p in client.iter_pages("Root")]
        self.assertEqual(titles, ["Root/A", "Root/B"])

    def test_iter_pages_records_failed(self):
        pages = {
            f"{BASE}/wiki/Special:PrefixIndex/Root": prefix_html("Root/Bad", "Root/Good"),
            f"{BASE}/wiki/Root/Good": page_html("Root/Good"),
        }
        session = FakeSession(pages, errors={f"{BASE}/wiki/Root/Bad"})
        client = HtmlClient(session, retry_delay=0)
        failed = []
        titles = [p.title for p in client.iter_pages("Root", failed=failed)]
        self.assertEqual(titles, ["Root/Good"])
        self.assertEqual(failed, ["Root/Bad"])

    def test_iter_pages_seeds_come_first_and_dedup(self):
        pages = {
            f"{BASE}/wiki/Special:PrefixIndex/Root": prefix_html("Root/A", "Root/B"),
            f"{BASE}/wiki/Root/A": page_html("Root/A"),
            f"{BASE}/wiki/Root/B": page_html("Root/B"),
            f"{BASE}/wiki/Root/Seed": page_html("Root/Seed"),
        }
        client = HtmlClient(FakeSession(pages))
        titles = [
            p.title for p in client.iter_pages("Root", seeds=["Root/Seed", "Root/A"])
        ]
        self.assertEqual(titles, ["Root/Seed", "Root/A", "Root/B"])

    def test_iter_pages_known_cache_avoids_refetch(self):
        pages = {
            f"{BASE}/wiki/Special:PrefixIndex/Root": prefix_html("Root/A", "Root/B"),
            f"{BASE}/wiki/Root/B": page_html("Root/B"),
        }
        session = FakeSession(pages)
        client = HtmlClient(session)
        known = {"Root/A": PageContent("Root/A", 1, "", "")}
        titles = [p.title for p in client.iter_pages("Root", known=known)]
        self.assertEqual(titles, ["Root/A", "Root/B"])
        self.assertNotIn(f"{BASE}/wiki/Root/A", session.requested)
        self.assertIn("Root/B", known)


if __name__ == "__main__":
    unittest.main()