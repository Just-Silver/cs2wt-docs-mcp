"""Anubis proof-of-work solver.

The Valve Developer Community wiki sits behind `Anubis
<https://github.com/TecharoHQ/anubis>`_, a reverse proxy that gates every
request behind a SHA-256 proof-of-work challenge.

When a request is challenged the proxy returns HTTP 200 with an HTML page that
embeds the challenge parameters as JSON::

    <script id="anubis_challenge" type="application/json">{...}</script>

The client must find a nonce such that::

    hex(sha256(random_data + str(nonce)))

starts with ``difficulty`` zero hex characters, then submit ``nonce`` and the
digest to ``/.within.website/x/cmd/anubis/api/pass-challenge``.  On success the
proxy sets an auth cookie that is valid for roughly seven days.

The challenge is bound to the requesting ``User-Agent`` and client IP, so the
same UA must be used for the whole session.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

_CHALLENGE_RE = re.compile(
    rb'<script id="anubis_challenge" type="application/json">(.*?)</script>',
    re.DOTALL,
)


@dataclass(frozen=True)
class Challenge:
    """Parsed Anubis challenge parameters."""

    id: str
    random_data: str
    difficulty: int
    algorithm: str

    @classmethod
    def from_json(cls, payload: dict) -> "Challenge":
        rules = payload.get("rules") or {}
        chal = payload.get("challenge") or {}
        return cls(
            id=chal["id"],
            random_data=chal["randomData"],
            difficulty=int(rules.get("difficulty", 0)),
            algorithm=str(rules.get("algorithm", "fast")),
        )


def parse_challenge(body: bytes) -> Challenge | None:
    """Return the challenge embedded in ``body``, or ``None`` if not challenged."""
    match = _CHALLENGE_RE.search(body)
    if not match:
        return None
    try:
        payload = json.loads(match.group(1))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return Challenge.from_json(payload)


def solve(challenge: Challenge) -> tuple[int, str]:
    """Brute-force a valid nonce.

    Returns ``(nonce, digest)`` where ``digest`` is the hex SHA-256 that
    satisfies the difficulty requirement.
    """
    prefix = "0" * challenge.difficulty
    data = challenge.random_data.encode()
    nonce = 0
    while True:
        digest = hashlib.sha256(data + str(nonce).encode()).hexdigest()
        if digest.startswith(prefix):
            return nonce, digest
        nonce += 1