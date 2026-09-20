import tempfile
import unittest
from pathlib import Path

from cs2wt.index import DocIndex


class DocIndexOptionsTest(unittest.TestCase):
    def test_wal_enabled(self):
        with tempfile.TemporaryDirectory() as d:
            idx = DocIndex(Path(d) / "a.sqlite", wal=True)
            mode = idx.conn.execute("PRAGMA journal_mode").fetchone()[0]
            self.assertEqual(mode.lower(), "wal")
            idx.close()

    def test_wal_default_off(self):
        with tempfile.TemporaryDirectory() as d:
            idx = DocIndex(Path(d) / "b.sqlite")
            mode = idx.conn.execute("PRAGMA journal_mode").fetchone()[0]
            self.assertNotEqual(mode.lower(), "wal")
            idx.close()

    def test_check_same_thread_false(self):
        with tempfile.TemporaryDirectory() as d:
            idx = DocIndex(Path(d) / "c.sqlite", check_same_thread=False)
            self.assertEqual(idx.count(), 0)
            idx.close()


if __name__ == "__main__":
    unittest.main()