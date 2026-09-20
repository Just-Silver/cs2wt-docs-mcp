"""Offline unit tests for incremental sync.

A fake wiki client is injected so these tests never touch the network.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cs2wt.index import DocIndex
from cs2wt.sync import sync
from cs2wt.wiki import PageContent


def page(pageid, title, revid):
    return {
        "pageid": pageid,
        "title": title,
        "revid": revid,
        "timestamp": "2026-01-01T00:00:00Z",
    }


class FakeClient:
    api_url = "fake://api"

    def __init__(self, pages, contents):
        self.pages = [dict(p) for p in pages]
        self.contents = dict(contents)
        self.fetched_titles = []

    def iter_pages_with_revisions(self, prefix, namespace=0):
        for p in self.pages:
            yield dict(p)

    def fetch_pages(self, titles):
        by_title = {p["title"]: p for p in self.pages}
        result = []
        for title in titles:
            self.fetched_titles.append(title)
            p = by_title[title]
            result.append(
                PageContent(
                    pageid=p["pageid"],
                    title=p["title"],
                    revid=p["revid"],
                    timestamp=p["timestamp"],
                    content=self.contents[p["pageid"]],
                )
            )
        return result


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
        client = FakeClient([page(1, "A", 10), page(2, "B", 20)], {1: "alpha", 2: "beta"})
        report = sync(client, prefix="P", data_dir=self.data, db_path=self.db)

        self.assertEqual(sorted(report.added), [1, 2])
        self.assertEqual(report.updated, [])
        self.assertEqual(report.removed, [])
        self.assertEqual(report.unchanged, [])
        self.assertEqual(self._count(), 2)
        self.assertEqual(self._manifest()["page_count"], 2)
        self.assertTrue((self.data / "raw" / "1.wiki").exists())

    def test_no_change_is_a_noop(self):
        pages = [page(1, "A", 10), page(2, "B", 20)]
        contents = {1: "alpha", 2: "beta"}
        sync(FakeClient(pages, contents), prefix="P", data_dir=self.data, db_path=self.db)

        client = FakeClient(pages, contents)
        report = sync(client, prefix="P", data_dir=self.data, db_path=self.db)

        self.assertEqual(sorted(report.unchanged), [1, 2])
        self.assertEqual(report.added, [])
        self.assertEqual(report.updated, [])
        self.assertEqual(report.removed, [])
        self.assertEqual(client.fetched_titles, [])

    def test_revid_change_updates_page(self):
        sync(
            FakeClient([page(1, "A", 10)], {1: "old"}),
            prefix="P",
            data_dir=self.data,
            db_path=self.db,
        )
        report = sync(
            FakeClient([page(1, "A", 11)], {1: "new"}),
            prefix="P",
            data_dir=self.data,
            db_path=self.db,
        )

        self.assertEqual(report.updated, [1])
        self.assertEqual(report.added, [])
        self.assertEqual(self._manifest()["pages"][0]["revid"], 11)
        index = DocIndex(self.db)
        self.assertIn("new", index.get(1)["content"])
        index.close()

    def test_title_move_is_an_update(self):
        sync(
            FakeClient([page(1, "Old Name", 10)], {1: "body"}),
            prefix="P",
            data_dir=self.data,
            db_path=self.db,
        )
        report = sync(
            FakeClient([page(1, "New Name", 10)], {1: "body"}),
            prefix="P",
            data_dir=self.data,
            db_path=self.db,
        )

        self.assertEqual(report.updated, [1])
        self.assertEqual(self._manifest()["pages"][0]["title"], "New Name")
        index = DocIndex(self.db)
        self.assertEqual(index.get(1)["title"], "New Name")
        index.close()

    def test_removed_page_drops_from_index_but_keeps_raw(self):
        sync(
            FakeClient([page(1, "A", 10), page(2, "B", 20)], {1: "alpha", 2: "beta"}),
            prefix="P",
            data_dir=self.data,
            db_path=self.db,
        )
        report = sync(
            FakeClient([page(1, "A", 10)], {1: "alpha"}),
            prefix="P",
            data_dir=self.data,
            db_path=self.db,
        )

        self.assertEqual(report.removed, [2])
        self.assertEqual(self._count(), 1)
        self.assertEqual(self._manifest()["page_count"], 1)
        # raw file is kept as an archive
        self.assertTrue((self.data / "raw" / "2.wiki").exists())

    def test_dry_run_reports_without_writing(self):
        client = FakeClient([page(1, "A", 10)], {1: "alpha"})
        report = sync(
            client, prefix="P", data_dir=self.data, db_path=self.db, dry_run=True
        )

        self.assertEqual(report.added, [1])
        self.assertFalse((self.data / "manifest.json").exists())
        self.assertFalse(self.db.exists())
        self.assertEqual(client.fetched_titles, [])


if __name__ == "__main__":
    unittest.main()