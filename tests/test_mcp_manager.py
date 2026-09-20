import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from cs2wt.index import DocIndex
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


def seed_index(cfg: ServerConfig) -> None:
    index = DocIndex(cfg.db)
    index.upsert(
        pageid=1,
        title="Page",
        content="hello world",
        revid=1,
        timestamp="t",
        url="u",
    )
    index.commit()
    index.close()


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

    def test_close_prevents_reopen_by_refresh_thread(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = make_config(d, refresh=True)
            seed_index(cfg)
            entered = threading.Event()
            release = threading.Event()

            def slow_refresh(config, has_index):
                entered.set()
                release.wait(5)

            mgr = IndexManager(cfg, refresher=slow_refresh)
            mgr.start()
            self.assertTrue(entered.wait(5))

            mgr.close()
            self.assertIsNone(mgr._reader)

            release.set()
            mgr.join(5)

            # The refresh thread's finally must not resurrect the reader.
            self.assertIsNone(mgr._reader)
            self.assertEqual(mgr.search("hello"), [])

    def test_reopen_failure_keeps_previous_reader(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = make_config(d, refresh=False)
            seed_index(cfg)
            mgr = IndexManager(cfg)
            self.assertEqual(len(mgr.search("hello")), 1)

            with mock.patch(
                "cs2wt.mcp_manager.DocIndex", side_effect=sqlite3.Error("boom")
            ):
                mgr._reopen_reader()

            # The old reader must remain open and usable, not a dead handle.
            self.assertEqual(len(mgr.search("hello")), 1)
            self.assertIsNone(mgr.error)
            mgr.close()

    def test_corrupt_db_does_not_raise(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = make_config(d, refresh=False)
            cfg.db.write_bytes(b"not a database")

            mgr = IndexManager(cfg)

            self.assertEqual(mgr.state, "ERROR")
            self.assertIsNotNone(mgr.error)
            self.assertEqual(mgr.search("x"), [])
            mgr.close()


if __name__ == "__main__":
    unittest.main()