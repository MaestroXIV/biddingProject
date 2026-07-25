"""Polite, cache-first fetching layer (SPEC 4.6).

Two transports, chosen per host:

- **WBF** (`db.worldbridge.org`, plain HTTP) -> httpx. Fast, no JS needed.
- **EBL** (`db.eurobridge.org`) -> a real Chromium via Playwright. EBL sits
  behind a Cloudflare "Just a moment..." JavaScript challenge that no plain
  HTTP client can pass; a real browser executes the challenge JS and gets the
  page. We do NOT solve the challenge ourselves -- the browser does, exactly as
  it would for a human (SPEC 4.6: never circumvent beyond honest headers).

Fetching stays separate from parsing: every page is written to
data/rawcache/{site}/{tournid}/{name}.html before anyone parses it, and
re-parsing works entirely from cache with zero network.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx

USER_AGENT = "BoardBase/0.1 (personal research; gregor.rus14@gmail.com)"
MIN_INTERVAL = 1.0  # seconds between requests (SPEC 4.6: max ~1 req/sec)
CHALLENGE_MARKERS = ("just a moment", "enable javascript", "checking your browser")
# Cloudflare shows a human-solvable "Verify you are human" checkbox. Headed, we
# wait for a person to click it (once per session -- the persistent profile then
# reuses the clearance cookie). Headless can't be solved, so we fail fast.
CHALLENGE_TIMEOUT_INTERACTIVE = 300.0
CHALLENGE_TIMEOUT_HEADLESS = 30.0

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_ROOT = REPO_ROOT / "data" / "rawcache"
BROWSER_PROFILE = REPO_ROOT / "data" / "browserprofile"


def needs_browser(url: str) -> bool:
    return "eurobridge.org" in urlsplit(url).netloc


class Fetcher:
    """Cache-first fetcher with a shared 1 req/s throttle across both transports.

    Use as a context manager so the browser (if any) is launched once and its
    Cloudflare clearance cookie is reused for the whole run:

        with Fetcher() as f:
            f.get(url, cache_path)
    """

    def __init__(self, headless: bool | None = None) -> None:
        if headless is None:
            headless = os.environ.get("BOARDBASE_HEADLESS", "0") == "1"
        self.headless = headless
        self._last = 0.0
        self._prompted = False
        self._httpx: httpx.Client | None = None
        self._pw = None          # playwright instance
        self._ctx = None         # persistent browser context

    # -- lifecycle ----------------------------------------------------------
    def __enter__(self) -> "Fetcher":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        if self._httpx is not None:
            self._httpx.close()
            self._httpx = None
        if self._ctx is not None:
            self._ctx.close()
            self._ctx = None
        if self._pw is not None:
            self._pw.stop()
            self._pw = None

    def _throttle(self) -> None:
        wait = MIN_INTERVAL - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    # -- public -------------------------------------------------------------
    def get(self, url: str, cache_path: Path) -> bytes:
        if cache_path.exists():
            return cache_path.read_bytes()
        self._throttle()
        data = self._fetch_browser(url) if needs_browser(url) else self._fetch_httpx(url)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(data)
        return data

    # -- transports ---------------------------------------------------------
    def _fetch_httpx(self, url: str) -> bytes:
        if self._httpx is None:
            self._httpx = httpx.Client(follow_redirects=True, timeout=30.0)
        resp = self._httpx.get(url, headers={"User-Agent": USER_AGENT})
        if resp.status_code == 403:
            raise RuntimeError(
                f"403 for {url} -- unexpected for WBF; investigate before retrying."
            )
        resp.raise_for_status()
        return resp.content

    def _ensure_browser(self):
        if self._ctx is not None:
            return self._ctx
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        # Persistent context keeps the Cloudflare clearance cookie between runs,
        # so only the first page of a session pays the challenge cost.
        self._ctx = self._pw.chromium.launch_persistent_context(
            user_data_dir=str(BROWSER_PROFILE),
            headless=self.headless,
            locale="en-US",
        )
        return self._ctx

    def _fetch_browser(self, url: str) -> bytes:
        ctx = self._ensure_browser()
        page = ctx.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            self._wait_for_challenge(page, url)
            html = page.content()
        finally:
            page.close()
        return html.encode("utf-8")

    def _wait_for_challenge(self, page, url: str) -> None:
        """Block until Cloudflare's interstitial clears, or raise on timeout.

        Headed, this waits for a human to tick the "Verify you are human" box in
        the open window (then the persistent profile reuses the clearance cookie
        for the rest of the run). Headless can't solve it, so we fail fast.
        """
        def challenged() -> bool:
            title = (page.title() or "").lower()
            body = (page.content() or "").lower()
            return any(m in title or m in body[:2000] for m in CHALLENGE_MARKERS)

        if not challenged():
            return
        if self.headless:
            raise RuntimeError(
                f"Cloudflare challenge for {url} cannot be solved headless. "
                "Run headed (do not set BOARDBASE_HEADLESS=1) from a residential "
                "connection; do not try to solve it in code."
            )
        if not self._prompted:
            print(
                "\n" + "=" * 68
                + "\n  Cloudflare check: click the 'Verify you are human' checkbox"
                + "\n  in the Chromium window that just opened. Solve it ONCE; the"
                + "\n  rest of the fetch continues automatically.\n"
                + "=" * 68 + "\n",
                flush=True,
            )
            self._prompted = True
        deadline = time.monotonic() + CHALLENGE_TIMEOUT_INTERACTIVE
        while challenged():
            if time.monotonic() > deadline:
                raise RuntimeError(
                    f"Challenge for {url} not solved within "
                    f"{CHALLENGE_TIMEOUT_INTERACTIVE:.0f}s. Re-run and click the "
                    "checkbox in the window."
                )
            page.wait_for_timeout(1000)


def fetch(url: str, cache_path: Path) -> bytes:
    """One-shot convenience (spins a browser up/down if the url needs one)."""
    with Fetcher() as f:
        return f.get(url, cache_path)
