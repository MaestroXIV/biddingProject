"""Polite, cache-first fetching layer (SPEC 4.6).

Two transports, chosen per host:

- **WBF** (`db.worldbridge.org`, plain HTTP) -> httpx. Fast, no JS needed.
- **EBL** (`db.eurobridge.org`) -> the user's real Google Chrome, driven over
  the DevTools protocol. EBL sits behind a Cloudflare "Verify you are human"
  Turnstile challenge. No HTTP client can pass it, and a Playwright-launched
  browser is fingerprinted as automation and never clears the checkbox either.
  Real Chrome is not flagged, so a human ticks the box ONCE and we reuse that
  genuine session (a dedicated Chrome profile keeps the clearance cookie). We do
  NOT solve or spoof the challenge ourselves (SPEC 4.6: never circumvent beyond
  honest headers) -- a person solves it in their own browser.

Fetching stays separate from parsing: every page is written to
data/rawcache/{site}/{tournid}/{name}.html before anyone parses it, and
re-parsing works entirely from cache with zero network.
"""
from __future__ import annotations

import subprocess
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

import httpx

USER_AGENT = "BoardBase/0.1 (personal research; gregor.rus14@gmail.com)"
MIN_INTERVAL = 1.0  # seconds between requests (SPEC 4.6: max ~1 req/sec)
CHALLENGE_MARKERS = ("just a moment", "enable javascript", "checking your browser")
# Cloudflare shows a human-solvable "Verify you are human" checkbox. We wait for
# a person to click it once (the dedicated Chrome profile then reuses the
# clearance cookie for the rest of the run and future runs).
CHALLENGE_TIMEOUT_INTERACTIVE = 300.0

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_ROOT = REPO_ROOT / "data" / "rawcache"
# Dedicated Chrome profile: keeps EBL's Cloudflare clearance cookie between runs
# and stays out of the way of the user's day-to-day Chrome.
CHROME_PROFILE = REPO_ROOT / "data" / "chromeprofile"
CHROME_DEBUG_PORT = 9222
CHROME_APP = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def needs_browser(url: str) -> bool:
    return "eurobridge.org" in urlsplit(url).netloc


class Fetcher:
    """Cache-first fetcher with a shared 1 req/s throttle across both transports.

    Use as a context manager so the browser (if any) is launched once and its
    Cloudflare clearance cookie is reused for the whole run:

        with Fetcher() as f:
            f.get(url, cache_path)
    """

    def __init__(self, chrome_app: str = CHROME_APP) -> None:
        self.chrome_app = chrome_app
        self._last = 0.0
        self._prompted = False
        self._httpx: httpx.Client | None = None
        self._pw = None          # playwright instance
        self._ctx = None         # connected browser context (real Chrome)
        self._chrome: subprocess.Popen | None = None

    # -- lifecycle ----------------------------------------------------------
    def __enter__(self) -> "Fetcher":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        if self._httpx is not None:
            self._httpx.close()
            self._httpx = None
        if self._pw is not None:
            # Don't close the context: that would kill the real Chrome we
            # connected to. Just detach Playwright, then stop Chrome ourselves.
            self._pw.stop()
            self._pw = None
        self._ctx = None
        if self._chrome is not None:
            self._chrome.terminate()
            try:
                self._chrome.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._chrome.kill()
            self._chrome = None

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

        if not Path(self.chrome_app).exists():
            raise RuntimeError(
                f"Google Chrome not found at {self.chrome_app}. Install Chrome "
                "(brew install --cask google-chrome) or pass chrome_app=..."
            )
        self._launch_real_chrome()
        self._pw = sync_playwright().start()
        # Attach to the real Chrome we just launched and reuse its default
        # context, so cookies (incl. Cloudflare clearance) are the human's.
        browser = self._pw.chromium.connect_over_cdp(
            f"http://127.0.0.1:{CHROME_DEBUG_PORT}"
        )
        self._ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        return self._ctx

    def _launch_real_chrome(self) -> None:
        CHROME_PROFILE.mkdir(parents=True, exist_ok=True)
        self._chrome = subprocess.Popen(
            [
                self.chrome_app,
                f"--remote-debugging-port={CHROME_DEBUG_PORT}",
                f"--user-data-dir={CHROME_PROFILE}",
                "--no-first-run",
                "--no-default-browser-check",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Wait for the DevTools endpoint to come up.
        endpoint = f"http://127.0.0.1:{CHROME_DEBUG_PORT}/json/version"
        for _ in range(50):
            try:
                urllib.request.urlopen(endpoint, timeout=1).read()
                return
            except Exception:
                time.sleep(0.2)
        raise RuntimeError(
            "Real Chrome did not expose its DevTools port. Is another Chrome "
            f"already using --user-data-dir={CHROME_PROFILE}? Close it and retry."
        )

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
        """Block until Cloudflare's checkbox is solved by the human, or time out.

        Waits for a person to tick the "Verify you are human" box in the real
        Chrome window that opened. Solve it once; the dedicated Chrome profile
        keeps the clearance cookie for the rest of the run and future runs.
        """
        def challenged() -> bool:
            title = (page.title() or "").lower()
            body = (page.content() or "").lower()
            return any(m in title or m in body[:2000] for m in CHALLENGE_MARKERS)

        if not challenged():
            return
        if not self._prompted:
            print(
                "\n" + "=" * 68
                + "\n  Cloudflare check: switch to the Google Chrome window that"
                + "\n  just opened and tick 'Verify you are human'. Solve it ONCE;"
                + "\n  the rest of the fetch then continues automatically.\n"
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
