import contextlib
import io
import unittest
from pathlib import Path

from cs2wt import release
from cs2wt.mcp_config import ServerConfig
from cs2wt.store import default_data_dir


class ServerConfigTest(unittest.TestCase):
    def test_defaults(self):
        cfg = ServerConfig.from_sources([], env={})
        data_dir = default_data_dir()
        self.assertEqual(cfg.data_dir, data_dir)
        self.assertEqual(cfg.db, data_dir / "docs.sqlite")
        self.assertEqual(cfg.release_repo, release.DEFAULT_REPO)
        self.assertEqual(cfg.release_tag, release.RELEASE_TAG)
        self.assertEqual(cfg.check_interval, 86400)
        self.assertTrue(cfg.refresh)

    def test_env_overrides_defaults(self):
        cfg = ServerConfig.from_sources(
            [],
            env={
                "CS2WT_DATA_DIR": "D",
                "CS2WT_RELEASE_REPO": "me/fork",
                "CS2WT_RELEASE_TAG": "data-v2",
                "CS2WT_CHECK_INTERVAL": "3600",
            },
        )
        self.assertEqual(cfg.data_dir, Path("D"))
        self.assertEqual(cfg.db, Path("D") / "docs.sqlite")
        self.assertEqual(cfg.release_repo, "me/fork")
        self.assertEqual(cfg.release_tag, "data-v2")
        self.assertEqual(cfg.check_interval, 3600)

    def test_argv_overrides_env(self):
        cfg = ServerConfig.from_sources(
            [
                "--data-dir",
                "A",
                "--release-repo",
                "cli/repo",
                "--release-tag",
                "cli-tag",
                "--check-interval",
                "60",
            ],
            env={
                "CS2WT_DATA_DIR": "B",
                "CS2WT_RELEASE_REPO": "env/repo",
                "CS2WT_RELEASE_TAG": "env-tag",
                "CS2WT_CHECK_INTERVAL": "120",
            },
        )
        self.assertEqual(cfg.data_dir, Path("A"))
        self.assertEqual(cfg.release_repo, "cli/repo")
        self.assertEqual(cfg.release_tag, "cli-tag")
        self.assertEqual(cfg.check_interval, 60)

    def test_no_refresh_flag_and_env(self):
        self.assertFalse(ServerConfig.from_sources(["--no-refresh"], env={}).refresh)
        self.assertFalse(
            ServerConfig.from_sources([], env={"CS2WT_NO_REFRESH": "1"}).refresh
        )

    def test_explicit_db(self):
        cfg = ServerConfig.from_sources(["--db", "x.sqlite"], env={})
        self.assertEqual(cfg.db, Path("x.sqlite"))

    def test_api_flag_is_not_recognized(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                ServerConfig.from_sources(["--api", "http://example/api.php"], env={})


if __name__ == "__main__":
    unittest.main()