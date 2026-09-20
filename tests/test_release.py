import io
import json
import sqlite3
import sys
import tempfile
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cs2wt import release


class FakeResponse:
    """Minimal urlopen() response: context manager + chunked read()."""

    def __init__(self, payload: bytes):
        self._bio = io.BytesIO(payload)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, size: int = -1) -> bytes:
        return self._bio.read(size)


def make_config(tmp: str, **overrides) -> SimpleNamespace:
    data_dir = Path(tmp)
    values = {
        "data_dir": data_dir,
        "db": data_dir / "docs.sqlite",
        "release_repo": release.DEFAULT_REPO,
        "release_tag": release.RELEASE_TAG,
        "check_interval": 86400,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def seed_local_db(db: Path, generated_at: str) -> None:
    conn = sqlite3.connect(db)
    conn.executescript("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);")
    conn.execute(
        "INSERT INTO meta(key, value) VALUES ('generated_at', ?)", (generated_at,)
    )
    conn.commit()
    conn.close()


def seed_local_manifest(data_dir: Path, generated_at: str) -> None:
    (data_dir / "manifest.json").write_text(
        json.dumps({"generated_at": generated_at}), encoding="utf-8"
    )


def seed_last_check(data_dir: Path, checked_at: datetime) -> None:
    (data_dir / "last_check.json").write_text(
        json.dumps({"checked_at": checked_at.isoformat()}), encoding="utf-8"
    )


def manifest_bytes(generated_at: str) -> bytes:
    return json.dumps({"generated_at": generated_at}).encode("utf-8")


class AssetUrlTest(unittest.TestCase):
    def test_asset_url(self):
        self.assertEqual(
            release.asset_url("owner/repo", "data-latest", "docs.sqlite"),
            "https://github.com/owner/repo/releases/download/data-latest/docs.sqlite",
        )


class UpdateFromReleaseTest(unittest.TestCase):
    def test_first_run_downloads_db_and_manifest(self):
        db_bytes = b"SQLite format 3\x00remote-index-bytes"
        remote_at = "2026-01-01T00:00:00+00:00"
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_config(tmp)
            responses = [
                FakeResponse(manifest_bytes(remote_at)),
                FakeResponse(db_bytes),
            ]
            with mock.patch(
                "cs2wt.release.urllib.request.urlopen", side_effect=responses
            ):
                staged = release.update_from_release(cfg, has_index=False)

            self.assertIsNotNone(staged)
            self.assertEqual(staged, Path(cfg.db).with_name("docs.sqlite.tmp"))
            self.assertTrue(staged.exists())
            self.assertEqual(staged.read_bytes(), db_bytes)

            local = json.loads(
                (Path(tmp) / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(local, {"generated_at": remote_at})
            self.assertTrue((Path(tmp) / "last_check.json").exists())

    def test_same_version_skips_db_download(self):
        remote_at = "2026-01-01T00:00:00+00:00"
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_config(tmp)
            seed_local_db(cfg.db, remote_at)
            with mock.patch(
                "cs2wt.release.urllib.request.urlopen",
                return_value=FakeResponse(manifest_bytes(remote_at)),
            ) as urlopen:
                staged = release.update_from_release(cfg, has_index=True)

            self.assertIsNone(staged)
            self.assertEqual(urlopen.call_count, 1)
            self.assertIn("manifest.json", urlopen.call_args[0][0])
            self.assertTrue((Path(tmp) / "last_check.json").exists())

    def test_remote_newer_returns_tmp(self):
        local_at = "2026-01-01T00:00:00+00:00"
        remote_at = "2026-02-01T00:00:00+00:00"
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_config(tmp)
            seed_local_db(cfg.db, local_at)
            responses = [
                FakeResponse(manifest_bytes(remote_at)),
                FakeResponse(b"new-bytes"),
            ]
            with mock.patch(
                "cs2wt.release.urllib.request.urlopen", side_effect=responses
            ):
                staged = release.update_from_release(cfg, has_index=True)

            self.assertIsNotNone(staged)
            self.assertTrue(staged.exists())
            self.assertEqual(staged.read_bytes(), b"new-bytes")

    def test_naive_remote_manifest_compares(self):
        local_at = "2026-01-01T00:00:00+00:00"
        remote_at = "2026-02-01T00:00:00"  # naive, no timezone
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_config(tmp)
            seed_local_db(cfg.db, local_at)
            responses = [
                FakeResponse(manifest_bytes(remote_at)),
                FakeResponse(b"new-bytes"),
            ]
            with mock.patch(
                "cs2wt.release.urllib.request.urlopen", side_effect=responses
            ):
                staged = release.update_from_release(cfg, has_index=True)

            self.assertIsNotNone(staged)
            self.assertEqual(staged.read_bytes(), b"new-bytes")

    def test_non_dict_remote_manifest_treated_as_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_config(tmp)
            seed_local_db(cfg.db, "2026-01-01T00:00:00+00:00")
            responses = [
                FakeResponse(b"[]"),
                FakeResponse(b"new-bytes"),
            ]
            with mock.patch(
                "cs2wt.release.urllib.request.urlopen", side_effect=responses
            ):
                staged = release.update_from_release(cfg, has_index=True)

            self.assertIsNotNone(staged)
            self.assertEqual(staged.read_bytes(), b"new-bytes")

    def test_unparseable_remote_treated_as_update(self):
        local_at = "2026-01-01T00:00:00+00:00"
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_config(tmp)
            seed_local_db(cfg.db, local_at)
            responses = [
                FakeResponse(manifest_bytes("not-a-timestamp")),
                FakeResponse(b"new-bytes"),
            ]
            with mock.patch(
                "cs2wt.release.urllib.request.urlopen", side_effect=responses
            ):
                staged = release.update_from_release(cfg, has_index=True)

            self.assertIsNotNone(staged)
            self.assertEqual(staged.read_bytes(), b"new-bytes")

    def test_network_error_with_index_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_config(tmp)
            seed_local_db(cfg.db, "2026-01-01T00:00:00+00:00")
            with mock.patch(
                "cs2wt.release.urllib.request.urlopen",
                side_effect=urllib.error.URLError("offline"),
            ):
                staged = release.update_from_release(cfg, has_index=True)

            self.assertIsNone(staged)
            self.assertFalse((Path(tmp) / "last_check.json").exists())

    def test_network_error_without_index_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_config(tmp)
            with mock.patch(
                "cs2wt.release.urllib.request.urlopen",
                side_effect=urllib.error.URLError("offline"),
            ):
                with self.assertRaises(urllib.error.URLError):
                    release.update_from_release(cfg, has_index=False)


class ThrottleTest(unittest.TestCase):
    def test_recent_check_skips_without_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_config(tmp)
            seed_local_db(cfg.db, "2026-01-01T00:00:00+00:00")
            seed_last_check(Path(tmp), datetime.now(timezone.utc))
            with mock.patch(
                "cs2wt.release.urllib.request.urlopen"
            ) as urlopen:
                staged = release.update_from_release(cfg, has_index=True)

            self.assertIsNone(staged)
            urlopen.assert_not_called()

    def test_naive_last_check_skips_without_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_config(tmp)
            seed_local_db(cfg.db, "2026-01-01T00:00:00+00:00")
            seed_last_check(Path(tmp), datetime.now())  # naive, no tzinfo
            with mock.patch(
                "cs2wt.release.urllib.request.urlopen"
            ) as urlopen:
                staged = release.update_from_release(cfg, has_index=True)

            self.assertIsNone(staged)
            urlopen.assert_not_called()

    def test_stale_check_triggers_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_config(tmp)
            seed_local_db(cfg.db, "2026-01-01T00:00:00+00:00")
            seed_last_check(
                Path(tmp), datetime.now(timezone.utc) - timedelta(days=2)
            )
            responses = [
                FakeResponse(manifest_bytes("2026-02-01T00:00:00+00:00")),
                FakeResponse(b"new-bytes"),
            ]
            with mock.patch(
                "cs2wt.release.urllib.request.urlopen", side_effect=responses
            ) as urlopen:
                staged = release.update_from_release(cfg, has_index=True)

            self.assertIsNotNone(staged)
            self.assertTrue(urlopen.called)

    def test_no_index_ignores_throttle(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_config(tmp)
            seed_last_check(Path(tmp), datetime.now(timezone.utc))
            responses = [
                FakeResponse(manifest_bytes("2026-02-01T00:00:00+00:00")),
                FakeResponse(b"new-bytes"),
            ]
            with mock.patch(
                "cs2wt.release.urllib.request.urlopen", side_effect=responses
            ) as urlopen:
                staged = release.update_from_release(cfg, has_index=False)

            self.assertIsNotNone(staged)
            self.assertTrue(urlopen.called)


if __name__ == "__main__":
    unittest.main()