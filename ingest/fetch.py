"""Polite, cache-first fetching layer (SPEC 4.6).

Fetching is kept separate from parsing: every page is written to
data/rawcache/{site}/{tournid}/{name}.html before anyone parses it, and
re-parsing must work entirely from cache with zero network.
"""
from __future__ import annotations

import time
from pathlib import Path

import httpx

USER_AGENT = "BoardBase/0.1 (personal research; gregor.rus14@gmail.com)"
MIN_INTERVAL = 1.0  # seconds between requests (SPEC 4.6: max ~1 req/sec)

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_ROOT = REPO_ROOT / "data" / "rawcache"

_last_request = 0.0


def _throttle() -> None:
    global _last_request
    wait = MIN_INTERVAL - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    _last_request = time.monotonic()


def fetch(url: str, cache_path: Path) -> bytes:
    """Fetch url politely, writing raw bytes to cache_path first.

    Returns raw bytes (undecoded) so charset handling stays in the parser.
    WBF serves plain HTTP (https redirects to http) -- follow redirects,
    don't force TLS. EBL 403s on cloud IPs; we surface that, never retry harder.
    """
    if cache_path.exists():
        return cache_path.read_bytes()

    _throttle()
    with httpx.Client(follow_redirects=True, timeout=30.0) as client:
        resp = client.get(url, headers={"User-Agent": USER_AGENT})
    if resp.status_code == 403:
        raise RuntimeError(
            f"403 for {url} -- likely a datacenter/cloud IP block (SPEC 4.6). "
            "Run from a residential connection; do not retry harder."
        )
    resp.raise_for_status()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(resp.content)
    return resp.content
