import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cs2wt.http import assert_allowed_url

OK = [
    "https://developer.valvesoftware.com/wiki/Assault",
    "https://developer.valvesoftware.com/wiki/Path_corner",
    "https://developer.valvesoftware.com/.within.website/x/cmd/anubis/api/pass-challenge?id=1",
]
BAD = [
    "http://developer.valvesoftware.com/wiki/Assault",       # 非 https
    "https://example.com/wiki/Assault",                      # 非目标 host
    "https://developer.valvesoftware.com/w/api.php",         # Disallow
    "https://developer.valvesoftware.com/w/Special:Export",  # Disallow
    "https://developer.valvesoftware.com/wiki/Special:Export/Foo",
    "https://developer.valvesoftware.com/wiki/Assault?title=Special:X",
    "https://developer.valvesoftware.com/wiki/Assault?action=history",
    "https://developer.valvesoftware.com/wiki/Assault#top",  # fragment
    "https://developer.valvesoftware.com/index.php",         # 非 /wiki/
]


class GuardTest(unittest.TestCase):
    def test_allowed(self):
        for url in OK:
            assert_allowed_url(url)  # 不应抛错

    def test_disallowed(self):
        for url in BAD:
            with self.assertRaises(ValueError):
                assert_allowed_url(url)


if __name__ == "__main__":
    unittest.main()