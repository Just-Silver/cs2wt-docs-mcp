import tempfile
import threading
import unittest
from pathlib import Path

from cs2wt.mcp_config import ServerConfig
from cs2wt.mcp_manager import IndexManager


def make_config(tmp: str, refresh: bool) -> ServerConfig:
    return ServerConfig(
        data_dir=Path(tmp),
        db=Path(tmp) / "docs.sqlite",
        prefix="P",
        api="http://example/api.php",
        ua="UA",
        cookie=str(Path(tmp) / "cookies.txt"),
        delay=0.0,
        refresh=refresh,
    )


class IndexManagerTest(unittest.TestCase):
    def test_no_refresh_is_ready(self):
        with tempfile.TemporaryDirectory() as d:
            mgr = IndexManager(make_config(d, refresh=False))
            mgr.start()
            self.assertEqual(mgr.state, "READY")
            self.assertEqual(mgr.search("x"), [])
            mgr.close()

    def test_refresh_success_sets_ready(self):
        with tempfile.TemporaryDirectory() as d:
            done = threading.Event()

            def fake_refresh(config, has_index):
                done.set()

            mgr = IndexManager(make_config(d, refresh=True), refresher=fake_refresh)
            mgr.start()
            self.assertTrue(done.wait(5))
            mgr.join(5)
            self.assertEqual(mgr.state, "READY")
            mgr.close()

    def test_refresh_failure_sets_error(self):
        with tempfile.TemporaryDirectory() as d:
            def boom(config, has_index):
                raise RuntimeError("network down")

            mgr = IndexManager(make_config(d, refresh=True), refresher=boom)
            mgr.start()
            mgr.join(5)
            self.assertEqual(mgr.state, "ERROR")
            self.assertIn("network down", mgr.error)
            mgr.close()

    def test_info_shape(self):
        with tempfile.TemporaryDirectory() as d:
            mgr = IndexManager(make_config(d, refresh=False))
            mgr.start()
            info = mgr.info()
            self.assertIn("state", info)
            self.assertIn("count", info)
            mgr.close()


if __name__ == "__main__":
    unittest.main()