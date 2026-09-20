import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cs2wt import store


class StoreTest(unittest.TestCase):
    def test_slug_is_filesystem_safe(self):
        self.assertEqual(store.slug("Path corner"), "Path%20corner")
        self.assertEqual(store.slug("A/B:C"), "A%2FB%3AC")

    def test_raw_path_uses_html(self):
        path = store.raw_path("data", "Path corner")
        self.assertEqual(path.name, "Path%20corner.html")
        self.assertEqual(path.parent.name, "raw")

    def test_manifest_by_title(self):
        manifest = {"pages": [{"title": "A", "revid": 1}, {"title": "B", "revid": 2}]}
        self.assertEqual(store.manifest_by_title(manifest)["B"]["revid"], 2)


if __name__ == "__main__":
    unittest.main()