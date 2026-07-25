"""Fetch every page of a tournament into data/rawcache (SPEC 7.6 ingest flow).

Enumerate rounds from RoundTeams (increment qroundno until a round has no
matches), then per round fetch RoundTeams + each BoardDetails + handsacross.
Cache-first and polite (SPEC 4.6): re-running skips already-cached pages.
"""
from __future__ import annotations

import sys
from pathlib import Path

from fetch import CACHE_ROOT, Fetcher
import parse
from registry import TOURNAMENTS, Tournament

MAX_ROUNDS = 60  # safety cap


def cache_path(t: Tournament, name: str) -> Path:
    return CACHE_ROOT / t.site / str(t.tournid) / name


def crawl(t: Tournament, fetcher: Fetcher) -> dict:
    counts = {"rounds": 0, "roundteams": 0, "boarddetails": 0, "handsacross": 0}
    for rnd in range(1, MAX_ROUNDS + 1):
        rt_url = f"{t.base}RoundTeams.asp?qtournid={t.tournid}&qroundno={rnd}"
        rt_raw = fetcher.get(rt_url, cache_path(t, f"roundteams_r{rnd}.html"))
        rt = parse.parse_roundteams(rt_raw)
        if not rt.matches:
            print(f"[{t.key}] round {rnd}: no matches -> stop ({rnd - 1} rounds)")
            break
        counts["rounds"] += 1
        counts["roundteams"] += 1
        print(f"[{t.key}] round {rnd}: {len(rt.matches)} matches", flush=True)
        for m in rt.matches:
            bd_url = f"{t.base}BoardDetails.asp?qmatchid={m.ext_match_id}"
            fetcher.get(bd_url, cache_path(t, f"boarddetails_{m.ext_match_id}.html"))
            counts["boarddetails"] += 1
        ha_url = f"{t.base}handsacross.asp?qtournid={t.tournid}&qround={rnd}"
        fetcher.get(ha_url, cache_path(t, f"handsacross_r{rnd}.html"))
        counts["handsacross"] += 1
    return counts


def main(keys: list[str]) -> None:
    with Fetcher() as fetcher:
        for key in keys:
            t = TOURNAMENTS[key]
            print(f"=== crawling {t.key} ({t.site} {t.tournid}) ===", flush=True)
            counts = crawl(t, fetcher)
            print(f"=== {t.key} done: {counts} ===", flush=True)


if __name__ == "__main__":
    keys = sys.argv[1:] or list(TOURNAMENTS)
    main(keys)
