"""End-to-end check of the browser-driven EBL fetcher (SPEC 4.6).

Run this on a residential Mac, headed (a Chromium window will open and pass the
Cloudflare "Just a moment..." challenge for real):

    .venv/bin/python ingest/validate_ebl_fetch.py

It fetches ONE real EBL page through the browser transport and asserts it
parses to the §10 golden. It does not touch tests/fixtures/. Politeness: a
single request.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from fetch import Fetcher
import parse

RIGA_BASE = "https://db.eurobridge.org/repository/competitions/26riga/microsite/Asp/"
URL = RIGA_BASE + "BoardAcross.asp?qboard=001.01..2620"


def main() -> None:
    scratch = Path(tempfile.mkdtemp()) / "boardacross.html"
    print("Opening a Chromium window to pass the Cloudflare challenge...")
    with Fetcher(headless=False) as f:
        data = f.get(URL, scratch)
    ba = parse.parse_boardacross(data)
    d = ba.deal
    print(f"  fetched {len(data)} bytes")
    print(f"  board {d.board_no}, dealer {d.dealer}, vul {d.vul}")
    print(f"  North hand: {d.hand_n}  (golden 542.8.Q764.K8542)")
    print(f"  tooltips: {len(ba.auctions)}  (golden 30)")
    ok = (
        (d.board_no, d.dealer, d.vul) == (1, "N", "NONE")
        and d.hand_n == "542.8.Q764.K8542"
        and d.all_cards_ok()
        and len(ba.auctions) == 30
    )
    print("\nRESULT:", "PASS -- browser EBL fetch works end to end" if ok else "FAIL")
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
