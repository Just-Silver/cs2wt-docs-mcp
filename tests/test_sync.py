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

    def __init__(self, pages, missing=(), redirects=(), errors=()):
        self.pages = {p.title: p for p in pages}
        self.missing = set(missing)
        self.redirects = set(redirects)
        self.errors = set(errors)
        self.fetched = []

    def fetch_page(self, title):
        self.fetched.append(title)
        if title in self.errors:
            raise RuntimeError(f"boom: {title}")
        if title in self.missing:
            return None
        if title in self.redirects:
            # A redirect is a 200 page whose title is still the requested URL
            # title; only the body/canonical target differs.
            return PageContent(
                title=title,
                revid=None,
                timestamp="2026-01-01T00:00:00Z",
                html=(
                    f'<div id="mw-content-text">'
                    f'<span class="mw-redirectedfrom">(Redirected from {title})</span></div>'
                ),
                is_redirect=True,
            )
        return self.pages.get(title)

    def iter_pages(self, prefix, seeds=(), known=None, failed=None):
        known = {} if known is None else known
        titles = [prefix] + [t for t in self.pages if t.startswith(prefix) and t != prefix]
        titles += [t for t in self.redirects if t.startswith(prefix)]
        for title in titles:
            page_obj = known.get(title)
            if page_obj is None:
                try:
                    page_obj = self.fetch_page(title)
                except RuntimeError:
                    if failed is not None:
                        failed.append(title)
                    continue
                if page_obj is None or page_obj.is_redirect:
                    continue
                known[title] = page_obj
            if page_obj.is_redirect:
                continue
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

    def test_redirected_page_is_removed(self):
        sync(FakeClient([page("Root", 1, ["Root/A"]), page("Root/A", 10)]),
             prefix="Root", data_dir=self.data, db_path=self.db)
        # The page now 200-renders as a redirect; it must leave the corpus.
        report = sync(
            FakeClient([page("Root", 1, ["Root/A"])], redirects={"Root/A"}),
            prefix="Root", data_dir=self.data, db_path=self.db,
        )

        self.assertEqual(report.removed, ["Root/A"])
        self.assertNotIn("Root/A", report.updated)
        self.assertNotIn("Root/A", report.unchanged)
        self.assertNotIn("Root/A", report.added)
        self.assertEqual(self._count(), 1)
        self.assertNotIn("Root/A", [r["title"] for r in self._manifest()["pages"]])
        index = DocIndex(self.db)
        try:
            self.assertIsNone(index.get("Root/A"))
        finally:
            index.close()

    def test_title_move_drops_old_key_and_adds_new(self):
        sync(FakeClient([page("Root", 1, ["Root/Old"]), page("Root/Old", 10)]),
             prefix="Root", data_dir=self.data, db_path=self.db)
        # The page was moved: the old title now redirects to the new one.
        report = sync(
            FakeClient(
                [page("Root", 1, ["Root/New"]), page("Root/New", 10)],
                redirects={"Root/Old"},
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

    def test_transient_fetch_failure_keeps_page(self):
        pages = [page("Root", 1, ["Root/A"]), page("Root/A", 10)]
        sync(FakeClient(pages), prefix="Root", data_dir=self.data, db_path=self.db)

        report = sync(
            FakeClient(pages, errors={"Root/A"}),
            prefix="Root", data_dir=self.data, db_path=self.db,
        )

        self.assertIn("Root/A", report.failed)
        self.assertNotIn("Root/A", report.removed)
        index = DocIndex(self.db)
        try:
            self.assertIsNotNone(index.get("Root/A"))
        finally:
            index.close()

    def test_sync_self_heals_missing_index_entry(self):
        pages = [page("Root", 1, ["Root/A"]), page("Root/A", 10)]
        sync(FakeClient(pages), prefix="Root", data_dir=self.data, db_path=self.db)

        index = DocIndex(self.db)
        index.delete("Root/A")
        index.commit()
        index.close()

        report = sync(FakeClient(pages), prefix="Root", data_dir=self.data, db_path=self.db)

        self.assertIn("Root/A", report.unchanged)
        index = DocIndex(self.db)
        try:
            self.assertIsNotNone(index.get("Root/A"))
        finally:
            index.close()


if __name__ == "__main__":
    unittest.main()