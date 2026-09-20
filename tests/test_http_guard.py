import sys
import unittest
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cs2wt.http import _GuardedRedirectHandler, assert_allowed_url

OK = [
    "https://developer.valvesoftware.com/wiki/Assault",
    "https://developer.valvesoftware.com/wiki/Path_corner",
    "https://developer.valvesoftware.com/.within.website/x/cmd/anubis/api/pass-challenge?id=1",
    # PrefixIndex is the only Special: path allowed by robots.txt
    "https://developer.valvesoftware.com/wiki/Special:PrefixIndex/Counter-Strike_2_Workshop_Tools",
]
BAD = [
    "http://developer.valvesoftware.com/wiki/Assault",       # 非 https
    "https://example.com/wiki/Assault",                      # 非目标 host
    "https://developer.valvesoftware.com/w/api.php",         # Disallow
    "https://developer.valvesoftware.com/w/Special:Export",  # Disallow
    "https://developer.valvesoftware.com/wiki/Special:Export/Foo",
    "https://developer.valvesoftware.com/wiki/Special:AllPages",   # 其他 Special: 仍禁
    "https://developer.valvesoftware.com/wiki/Special:Random",
    "https://developer.valvesoftware.com/w/Special:X",
    "https://developer.valvesoftware.com/wiki/Special:PrefixIndex/X?from=Y",  # 带 query
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


class RedirectGuardTest(unittest.TestCase):
    def test_redirect_to_disallowed_is_blocked(self):
        handler = _GuardedRedirectHandler()
        req = urllib.request.Request("https://developer.valvesoftware.com/wiki/A")
        with self.assertRaises(ValueError):
            handler.redirect_request(req, None, 302, "Found", {}, "https://evil.example/wiki/B")

    def test_redirect_within_wiki_is_allowed(self):
        handler = _GuardedRedirectHandler()
        req = urllib.request.Request("https://developer.valvesoftware.com/wiki/A")
        result = handler.redirect_request(
            req, None, 302, "Found", {}, "https://developer.valvesoftware.com/wiki/B"
        )
        self.assertIsNotNone(result)


if __name__ == "__main__":
    unittest.main()