import json
import unittest

from cs2wt.mcp_tools import tool_get_page, tool_list_pages, tool_search_docs


class FakeManager:
    def __init__(self, state="READY", error=None):
        self.state = state
        self.error = error
        self.pages = {
            "Doc": {
                "pageid": 1,
                "title": "Doc",
                "url": "u",
                "revid": 2,
                "timestamp": "t",
                "content": "# Top\n\nintro\n\n## Alpha\n\nalpha body\n",
            }
        }

    def search(self, query, limit=10):
        return [{"pageid": 1, "title": "Doc", "url": "u", "snippet": "s", "score": 1.0}]

    def get(self, key):
        return self.pages.get(key)

    def list_titles(self):
        return [(1, "Doc")]


class ToolsTest(unittest.TestCase):
    def test_search(self):
        data = json.loads(tool_search_docs(FakeManager(), "x"))
        self.assertEqual(data["count"], 1)

    def test_get_full_page(self):
        data = json.loads(tool_get_page(FakeManager(), "Doc"))
        self.assertTrue(data["found"])
        self.assertIn("alpha body", data["content"])

    def test_get_section(self):
        data = json.loads(tool_get_page(FakeManager(), "Doc", section="Alpha"))
        self.assertTrue(data["found"])
        self.assertIn("alpha body", data["content"])
        self.assertNotIn("intro", data["content"])

    def test_get_missing_page(self):
        data = json.loads(tool_get_page(FakeManager(), "Nope"))
        self.assertFalse(data["found"])

    def test_get_missing_section(self):
        data = json.loads(tool_get_page(FakeManager(), "Doc", section="Nope"))
        self.assertFalse(data["found"])

    def test_list(self):
        data = json.loads(tool_list_pages(FakeManager()))
        self.assertEqual(data["count"], 1)

    def test_search_initializing(self):
        data = json.loads(tool_search_docs(FakeManager(state="INITIALIZING"), "x"))
        self.assertEqual(data["status"], "initializing")

    def test_get_missing_page_error_state(self):
        mgr = FakeManager(state="ERROR", error="DatabaseError: corrupt")
        data = json.loads(tool_get_page(mgr, "Nope"))
        self.assertFalse(data["found"])
        self.assertEqual(data["status"], "error")
        self.assertIn(mgr.error, data["message"])

    def test_search_refreshing(self):
        data = json.loads(tool_search_docs(FakeManager(state="REFRESHING"), "x"))
        self.assertEqual(data["count"], 1)
        self.assertTrue(data["refreshing"])


if __name__ == "__main__":
    unittest.main()