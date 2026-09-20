import unittest
from pathlib import Path

from cs2wt.mcp_config import ServerConfig


class ServerConfigTest(unittest.TestCase):
    def test_defaults(self):
        cfg = ServerConfig.from_sources([], env={})
        self.assertEqual(cfg.data_dir, Path("data"))
        self.assertEqual(cfg.db, Path("data") / "docs.sqlite")
        self.assertEqual(cfg.prefix, "Counter-Strike 2 Workshop Tools")
        self.assertTrue(cfg.refresh)

    def test_env_overrides_defaults(self):
        cfg = ServerConfig.from_sources(
            [], env={"CS2WT_DATA_DIR": "D", "CS2WT_DELAY": "2.5"}
        )
        self.assertEqual(cfg.data_dir, Path("D"))
        self.assertEqual(cfg.db, Path("D") / "docs.sqlite")
        self.assertEqual(cfg.delay, 2.5)

    def test_argv_overrides_env(self):
        cfg = ServerConfig.from_sources(
            ["--data-dir", "A", "--prefix", "P"], env={"CS2WT_DATA_DIR": "B"}
        )
        self.assertEqual(cfg.data_dir, Path("A"))
        self.assertEqual(cfg.prefix, "P")

    def test_no_refresh_flag_and_env(self):
        self.assertFalse(ServerConfig.from_sources(["--no-refresh"], env={}).refresh)
        self.assertFalse(
            ServerConfig.from_sources([], env={"CS2WT_NO_REFRESH": "1"}).refresh
        )

    def test_explicit_db(self):
        cfg = ServerConfig.from_sources(["--db", "x.sqlite"], env={})
        self.assertEqual(cfg.db, Path("x.sqlite"))


if __name__ == "__main__":
    unittest.main()