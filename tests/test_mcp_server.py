import tempfile
import unittest
from pathlib import Path

import anyio
from mcp import Client

from cs2wt.mcp_config import ServerConfig
from cs2wt.mcp_manager import IndexManager
from cs2wt.mcp_server import build_server


def make_config(tmp: str) -> ServerConfig:
    return ServerConfig(
        data_dir=Path(tmp),
        db=Path(tmp) / "docs.sqlite",
        prefix="P",
        ua="UA",
        cookie=str(Path(tmp) / "cookies.txt"),
        delay=0.0,
        refresh=False,
    )


class ServerTest(unittest.TestCase):
    def test_tools_registered(self):
        with tempfile.TemporaryDirectory() as d:
            mgr = IndexManager(make_config(d))
            mgr.start()
            server = build_server(mgr)

            async def go():
                async with Client(server) as client:
                    listed = await client.list_tools()
                    return {t.name for t in listed.tools}

            names = anyio.run(go)
            self.assertEqual(names, {"search_docs", "get_page", "list_pages"})
            mgr.close()

    def test_call_list_pages_empty_index(self):
        with tempfile.TemporaryDirectory() as d:
            mgr = IndexManager(make_config(d))
            mgr.start()
            server = build_server(mgr)

            async def go():
                async with Client(server) as client:
                    return await client.call_tool("list_pages", {})

            result = anyio.run(go)
            self.assertIn('"count": 0', result.content[0].text)
            mgr.close()


if __name__ == "__main__":
    unittest.main()