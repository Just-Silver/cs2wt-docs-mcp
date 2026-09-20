"""HTTP client that transparently passes Anubis challenges.

Wraps :mod:`urllib` with a persistent cookie jar.  The first request to a
challenged host solves the proof-of-work, stores the resulting auth cookie on
disk, and retries.  Later requests (within the cookie's ~7 day lifetime) skip
the challenge entirely.
"""

from __future__ import annotations

import http.cookiejar
import time
import urllib.parse
import urllib.request
from pathlib import Path

from .anubis import parse_challenge, solve

PASS_PATH = "/.within.website/x/cmd/anubis/api/pass-challenge"
DEFAULT_UA = "cs2wt-docs/0.1 (+local documentation indexer)"

ALLOWED_HOST = "developer.valvesoftware.com"
ANUBIS_PATH_PREFIX = "/.within.website/"


def assert_allowed_url(url: str) -> None:
    """Enforce the robots.txt contract: only GET /wiki/<title> on the VDC host.

    The Anubis PoW handshake path is transport infrastructure, not a crawl
    request, so it is exempt.
    """
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or parts.netloc != ALLOWED_HOST:
        raise ValueError(f"disallowed host/scheme: {url!r}")
    if parts.path.startswith(ANUBIS_PATH_PREFIX):
        return
    if parts.query or parts.fragment:
        raise ValueError(f"disallowed query/fragment: {url!r}")
    if not parts.path.startswith("/wiki/"):
        raise ValueError(f"disallowed path: {url!r}")
    if "/w/" in parts.path or "Special:" in parts.path:
        raise ValueError(f"disallowed path: {url!r}")


class _GuardedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Re-validate the target of every redirect against the robots contract."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        assert_allowed_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class AnubisSession:
    """A minimal throttled HTTP session with automatic PoW solving."""

    def __init__(
        self,
        *,
        user_agent: str = DEFAULT_UA,
        cookie_path: str | Path | None = None,
        delay: float = 1.0,
        timeout: float = 30.0,
    ) -> None:
        self.user_agent = user_agent
        self.delay = delay
        self.timeout = timeout
        self._last_request = 0.0

        self.jar = http.cookiejar.MozillaCookieJar(
            str(cookie_path) if cookie_path else None
        )
        if cookie_path and Path(cookie_path).exists():
            try:
                self.jar.load(ignore_discard=True, ignore_expires=True)
            except (OSError, http.cookiejar.LoadError):
                pass

        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar),
            _GuardedRedirectHandler(),
        )

    # -- internals ---------------------------------------------------------

    def _throttle(self) -> None:
        wait = self.delay - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    def _open(self, url: str) -> tuple[bytes, str]:
        assert_allowed_url(url)
        self._throttle()
        request = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
        with self._opener.open(request, timeout=self.timeout) as response:
            return response.read(), response.geturl()

    def _pass_challenge(self, challenge, target: str) -> None:
        nonce, digest = solve(challenge)
        params = urllib.parse.urlencode(
            {
                "id": challenge.id,
                "response": digest,
                "nonce": nonce,
                "redir": target,
                "elapsedTime": 0,
            }
        )
        parts = urllib.parse.urlsplit(target)
        pass_url = urllib.parse.urlunsplit(
            (parts.scheme, parts.netloc, PASS_PATH, params, "")
        )
        self._open(pass_url)
        self.save_cookies()

    # -- public API --------------------------------------------------------

    def get(self, url: str) -> bytes:
        """GET ``url``, solving an Anubis challenge if one is presented."""
        body, _ = self._open(url)
        challenge = parse_challenge(body)
        if challenge is None:
            return body
        self._pass_challenge(challenge, url)
        body, _ = self._open(url)
        return body

    def save_cookies(self) -> None:
        if not self.jar.filename:
            return
        try:
            self.jar.save(ignore_discard=True, ignore_expires=True)
        except OSError:
            pass