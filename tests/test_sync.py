"""Offline unit tests for incremental sync (fake HTML client, no network)."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cs2wt.index import DocIndex
from cs2wt.sync import sync
from cs2wt.wiki import PageContent


def page(title, revid, links=()):
    anchors = "".join(f'<a href="/wiki/{link}">{link}</a>' for link in links)
    return PageContent(
        title=title,
        revid=revid,
        timestamp="2026-01-01T00:00:00Z",
        html=f'<div id="mw-content-text"><p>{title} body</p>{anchors}</div>',
    )


class FakeClient:
    base_url = "https://developer.valvesoftware.com"

    def __init__(self, pages, missing=(), redirects=None):
        self.pages = {p.title: p for p in pages}
        self.missing = set(missing)
        self.redirects = dict(redirects or {})
        self.fetched = []

    def fetch_page(self, title):
        self.fetched.append(title)
        if title in self.missing:
            return None
        return self.pages.get(self.redirects.get(title, title))

    def iter_pages(self, prefix, seeds=(), known=None):
        known = {} if known is None else known
        titles = [prefix] + [t for t in self.pages if t.startswith(prefix) and t != prefix]
        for title in titles:
            page_obj = known.get(title) or self.fetch_page(title)
            if page_obj is None:
                continue
            known[title] = page_obj
            yield page_obj


class SyncTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.data = Path(self._tmp.name) / "data"
        self.data.mkdir()
        self.db = self.data / "docs.sqlite"

    def tearDown(self):
        self._tmp.cleanup()

    def _manifest(self):
        return json.loads((self.data / "manifest.json").read_text(encoding="utf-8"))

    def _count(self):
        index = DocIndex(self.db)
        try:
            return index.count()
        finally:
            index.close()

    def test_first_sync_adds_everything(self):
        client = FakeClient([page("Root", 1, ["Root/A", "Root/B"]), page("Root/A", 10), page("Root/B", 20)])
        report = sync(client, prefix="Root", data_dir=self.data, db_path=self.db)

        self.assertEqual(sorted(report.added), ["Root", "Root/A", "Root/B"])
        self.assertEqual(report.updated, [])
        self.assertEqual(report.removed, [])
        self.assertEqual(self._count(), 3)
        self.assertTrue((self.data / "raw" / "Root%2FA.html").exists())

    def test_no_change_is_a_noop(self):
        pages = [page("Root", 1, ["Root/A"]), page("Root/A", 10)]
        sync(FakeClient(pages), prefix="Root", data_dir=self.data, db_path=self.db)
        client = FakeClient(pages)
        report = sync(client, prefix="Root", data_dir=self.data, db_path=self.db)

        self.assertEqual(sorted(report.unchanged), ["Root", "Root/A"])
        self.assertEqual(report.added + report.updated + report.removed, [])

    def test_revid_change_updates_page(self):
        sync(FakeClient([page("Root", 1, ["Root/A"]), page("Root/A", 10)]),
             prefix="Root", data_dir=self.data, db_path=self.db)
        report = sync(FakeClient([page("Root", 1, ["Root/A"]), page("Root/A", 11)]),
                      prefix="Root", data_dir=self.data, db_path=self.db)

        self.assertEqual(report.updated, ["Root/A"])
        index = DocIndex(self.db)
        self.assertIn("Root/A body", index.get("Root/A")["content"])
        index.close()

    def test_removed_page_drops_from_index_but_keeps_raw(self):
        sync(FakeClient([page("Root", 1, ["Root/A", "Root/B"]), page("Root/A", 10), page("Root/B", 20)]),
             prefix="Root", data_dir=self.data, db_path=self.db)
        report = sync(
            FakeClient([page("Root", 1, ["Root/A"]), page("Root/A", 10)], missing={"Root/B"}),
            prefix="Root", data_dir=self.data, db_path=self.db,
        )

        self.assertEqual(report.removed, ["Root/B"])
        self.assertEqual(self._count(), 2)
        self.assertTrue((self.data / "raw" / "Root%2FB.html").exists())

    def test_title_move_drops_old_key_and_adds_new(self):
        sync(FakeClient([page("Root", 1, ["Root/Old"]), page("Root/Old", 10)]),
             prefix="Root", data_dir=self.data, db_path=self.db)
        # The page was moved: the old title now redirects to the new one.
        report = sync(
            FakeClient(
                [page("Root", 1, ["Root/New"]), page("Root/New", 10)],
                redirects={"Root/Old": "Root/New"},
            ),
            prefix="Root", data_dir=self.data, db_path=self.db,
        )

        self.assertEqual(report.removed, ["Root/Old"])
        self.assertEqual(report.added, ["Root/New"])
        index = DocIndex(self.db)
        self.assertIsNone(index.get("Root/Old"))
        self.assertIsNotNone(index.get("Root/New"))
        index.close()

    def test_dry_run_fetches_but_writes_nothing(self):
        client = FakeClient([page("Root", 1, ["Root/A"]), page("Root/A", 10)])
        report = sync(client, prefix="Root", data_dir=self.data, db_path=self.db, dry_run=True)

        self.assertEqual(sorted(report.added), ["Root", "Root/A"])
        self.assertFalse((self.data / "manifest.json").exists())
        self.assertFalse(self.db.exists())


if __name__ == "__main__":
    unittest.main()