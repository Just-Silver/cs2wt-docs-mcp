import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cs2wt.index import DocIndex, page_url


class DocIndexTitleTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.idx = DocIndex(Path(self._tmp.name) / "docs.sqlite")

    def tearDown(self):
        self.idx.close()
        self._tmp.cleanup()

    def _put(self, title, revid, content):
        self.idx.upsert(
            title=title, content=content, revid=revid,
            timestamp="t", url=page_url(title),
        )

    def test_upsert_and_search_has_no_pageid(self):
        self._put("Alpha", 1, "hello world")
        hits = self.idx.search("hello")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["title"], "Alpha")
        self.assertNotIn("pageid", hits[0])

    def test_rowid_is_stable_across_updates(self):
        self._put("Alpha", 1, "one")
        self.assertEqual(self.idx.get(1)["title"], "Alpha")
        self._put("Alpha", 2, "two")
        second = self.idx.get("Alpha")
        self.assertEqual(second["revid"], 2)
        self.assertIn("two", second["content"])
        self.assertEqual(self.idx.count(), 1)
        # rowid must be reused across updates (stable per-page id)
        self.assertEqual(self.idx.get(1)["revid"], 2)
        self.assertIsNone(self.idx.get(2))

    def test_rowid_reused_when_other_pages_exist(self):
        # A single-page table cannot tell rowid reuse apart from a naive
        # delete+insert (SQLite would hand the empty table rowid 1 again).
        # With a second page present, only true reuse keeps Alpha on rowid 1.
        self._put("Alpha", 1, "one")
        self._put("Beta", 1, "b")
        self.assertEqual(self.idx.get(1)["title"], "Alpha")
        self._put("Alpha", 2, "two")
        self.assertEqual(self.idx.get(1)["revid"], 2)
        self.assertIn("two", self.idx.get(1)["content"])
        self.assertIsNone(self.idx.get(3))
        self.assertEqual(self.idx.count(), 2)

    def test_get_by_rowid_and_title(self):
        self._put("Alpha", 1, "one")
        self.assertEqual(self.idx.get("Alpha")["title"], "Alpha")
        # 首条插入的 rowid 为 1，纯数字走 rowid 查询
        self.assertEqual(self.idx.get(1)["title"], "Alpha")
        self.assertIsNone(self.idx.get(999))

    def test_delete_by_title(self):
        self._put("Alpha", 1, "one")
        self.idx.delete("Alpha")
        self.assertEqual(self.idx.count(), 0)

    def test_list_titles_returns_strings(self):
        self._put("B", 1, "b")
        self._put("A", 1, "a")
        self.assertEqual(self.idx.list_titles(), ["A", "B"])


if __name__ == "__main__":
    unittest.main()