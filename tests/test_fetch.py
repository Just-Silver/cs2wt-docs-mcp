import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cs2wt.fetch import crawl
from cs2wt.wiki import PageContent


class FakeClient:
    base_url = "https://developer.valvesoftware.com"

    def __init__(self, pages):
        self._pages = pages

    def iter_pages(self, prefix, seeds=(), known=None):
        # The real client BFS-discovers the tree; this fake yields the fixed set
        # of pages it holds, treating them as already reachable from ``prefix``.
        for title in dict.fromkeys([prefix, *seeds, *self._pages]):
            page = self._pages.get(title)
            if page is not None:
                yield page


def page(title, revid):
    return PageContent(title=title, revid=revid, timestamp="t", html=f"<h1>{title}</h1>")


class FetchTest(unittest.TestCase):
    def test_crawl_writes_html_and_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            client = FakeClient({"Root": page("Root", 1), "A": page("A", 2)})
            manifest = crawl(client, prefix="Root", out_dir=d)

            self.assertEqual((Path(d) / "raw" / "Root.html").read_text(encoding="utf-8"), "<h1>Root</h1>")
            self.assertEqual((Path(d) / "raw" / "A.html").exists(), True)
            titles = [record["title"] for record in manifest["pages"]]
            self.assertEqual(titles, ["A", "Root"])
            self.assertEqual(manifest["pages"][0]["file"], "raw/A.html")
            self.assertEqual(manifest["source"], client.base_url)
            on_disk = json.loads((Path(d) / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(on_disk["page_count"], 2)


if __name__ == "__main__":
    unittest.main()