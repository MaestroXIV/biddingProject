"""Fetch every page of a tournament into data/rawcache (SPEC 7.6 ingest flow).

Dispatches on Tournament.kind (PAIRS_KO.md §3):

- teams: enumerate rounds from RoundTeams (increment qroundno until a round has
  no matches), then per round fetch RoundTeams + each BoardDetails + handsacross.
- ko:    Knockoutphase entry -> phases -> per phase the match (segment) ids ->
  BoardDetailsKO per id -> HandsAcrossKO per (phase, segment).
- pairs: TotalPairs entry -> phases -> per (phase, session) every
  BoardAcrossPairs traveller of the session.

Cache-first and polite (SPEC 4.6): re-running skips already-cached pages.
Missing pages are logged and skipped, never fatal (except the entry page).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from fetch import CACHE_ROOT, Fetcher
import parse
from registry import TOURNAMENTS, Tournament

MAX_ROUNDS = 60  # safety cap
KO_ENTRY_PHASES = ("FF", "SF", "QF", "16", "32", "64")
PAIRS_ENTRY_GROUPS = (1, 2, 6, 7, 8, 3, 4, 5)
MAX_SESSIONS = 30  # safety cap when a phase does not say its last session


def cache_dir(t: Tournament) -> Path:
    return CACHE_ROOT / t.site / str(t.tournid)


def cache_path(t: Tournament, name: str) -> Path:
    return cache_dir(t) / name


def entry_cache_name(t: Tournament) -> str:
    """The first page a crawl writes; its presence means 'this event is cached'."""
    return {"ko": "ko_entry.html", "pairs": "tp_entry.html"}.get(
        t.kind, "roundteams_r1.html")


def _log(t: Tournament, msg: str) -> None:
    print(f"[{t.key}] {msg}", flush=True)


def _get(fetcher: Fetcher, t: Tournament, url: str, name: str,
         counts: dict, what: str) -> bytes | None:
    """Fetch one page; on a transport/HTTP error log it, count it, return None."""
    try:
        return fetcher.get(url, cache_path(t, name))
    except Exception as e:
        key = f"{what}_missing"
        counts[key] = counts.get(key, 0) + 1
        _log(t, f"{what} missing: {name} ({e.__class__.__name__}: {e})")
        return None


def crawl(t: Tournament, fetcher: Fetcher) -> dict:
    if t.kind == "ko":
        return crawl_ko(t, fetcher)
    if t.kind == "pairs":
        return crawl_pairs(t, fetcher)
    return crawl_teams(t, fetcher)


# --- teams (unchanged flow) ----------------------------------------------------

def crawl_teams(t: Tournament, fetcher: Fetcher) -> dict:
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
        # handsacross is absent on some older microsites -- don't let a 404 kill
        # the crawl (deals can fall back to BoardAcross; SPEC 4.2 / 8.6).
        ha_url = f"{t.base}handsacross.asp?qtournid={t.tournid}&qround={rnd}"
        try:
            fetcher.get(ha_url, cache_path(t, f"handsacross_r{rnd}.html"))
            counts["handsacross"] += 1
        except Exception as e:
            counts.setdefault("handsacross_missing", 0)
            counts["handsacross_missing"] += 1
            if counts["handsacross_missing"] == 1:
                print(f"[{t.key}] handsacross missing ({e.__class__.__name__}); "
                      "continuing without it", flush=True)
    return counts


# --- knockout ------------------------------------------------------------------

def ko_phase_url(t: Tournament, phase: str) -> str:
    return f"{t.base}Knockoutphase.asp?qtournid={t.tournid}&qphase={phase}"


def _ko_entry(t: Tournament, fetcher: Fetcher) -> list[parse.Phase]:
    """ko_entry.html = the first Knockoutphase page that lists phases."""
    entry = cache_path(t, "ko_entry.html")
    for code in KO_ENTRY_PHASES:
        try:
            raw = fetcher.get(ko_phase_url(t, code), entry)
            phases = parse.parse_ko_phases(raw, t.tournid)
        except NotImplementedError:
            raise
        except Exception as e:
            _log(t, f"ko entry qphase={code}: {e.__class__.__name__}")
            phases = []
        if phases:
            return phases
        entry.unlink(missing_ok=True)   # not a working entry: don't keep it as one
    return []


def crawl_ko(t: Tournament, fetcher: Fetcher) -> dict:
    counts = {"phases": 0, "matches": 0, "boarddetails": 0, "handsacross": 0}
    phases = _ko_entry(t, fetcher)
    if not phases:
        raise RuntimeError(f"[{t.key}] no Knockoutphase entry page lists phases "
                           f"(tried qphase={','.join(KO_ENTRY_PHASES)})")
    _log(t, "ko phases: " + ", ".join(f"{p.code} ({p.name})" for p in phases))
    for ph in phases:
        raw = _get(fetcher, t, ko_phase_url(t, ph.code), f"ko_phase_{ph.code}.html",
                   counts, "ko_phase")
        if raw is None:
            continue
        try:
            mids = parse.parse_ko_match_ids(raw)
        except NotImplementedError:
            raise
        except Exception as e:
            _log(t, f"phase {ph.code}: unreadable ({e.__class__.__name__}: {e})")
            continue
        counts["phases"] += 1
        _log(t, f"phase {ph.code}: {len(mids)} match segments")
        segments: set[int] = set()
        for mid in mids:
            counts["matches"] += 1
            bd_raw = _get(fetcher, t,
                          f"{t.base}BoardDetailsKO.asp?qmatchid={mid}&qphase={ph.code}",
                          f"bdko_{mid}.html", counts, "boarddetails")
            if bd_raw is None:
                continue
            counts["boarddetails"] += 1
            try:
                seg = parse.parse_boarddetails(bd_raw).segment
            except NotImplementedError:
                raise
            except Exception as e:
                _log(t, f"bdko_{mid}: unreadable ({e.__class__.__name__}: {e})")
                continue
            if seg is None:
                _log(t, f"bdko_{mid}: no segment number -- skipped")
                continue
            segments.add(seg)
        for seg in sorted(segments):
            url = (f"{t.base}HandsAcrossKO.asp?qtournid={t.tournid}"
                   f"&qround={seg}&qphase={ph.code}")
            if _get(fetcher, t, url, f"hako_{ph.code}_r{seg}.html",
                    counts, "handsacross") is not None:
                counts["handsacross"] += 1
    return counts


# --- pairs ---------------------------------------------------------------------

def bap_url(t: Tournament, group: str | int, session: int, board: int) -> str:
    return (f"{t.base}BoardAcrossPairs.asp?qboard={board}&qtournid={t.tournid}"
            f"&qroundno={session}&qgroupno={group}&qdesktop=0")


def qboard_of(href: str) -> int | None:
    m = re.search(r"qboard=(\d+)", href, re.I)
    return int(m.group(1)) if m else None


def _pairs_entry(t: Tournament, fetcher: Fetcher) -> list[parse.Phase]:
    entry = cache_path(t, "tp_entry.html")
    for g in PAIRS_ENTRY_GROUPS:
        url = f"{t.base}TotalPairs.asp?qtournid={t.tournid}&qgroupno={g}&qroundno=1"
        try:
            raw = fetcher.get(url, entry)
            phases = parse.parse_pairs_phases(raw, t.tournid)
        except NotImplementedError:
            raise
        except Exception as e:
            _log(t, f"pairs entry qgroupno={g}: {e.__class__.__name__}")
            phases = []
        if phases:
            return phases
        entry.unlink(missing_ok=True)
    return []


def _first_board_from_totalpairs(t: Tournament, fetcher: Fetcher, group: str,
                                 session: int, counts: dict) -> int | None:
    """Fallback when board 1 is empty: the session ranking's first traveller link."""
    url = (f"{t.base}TotalPairs.asp?qtournid={t.tournid}&qgroupno={group}"
           f"&qroundno={session}")
    raw = _get(fetcher, t, url, f"tp_g{group}_r{session}.html", counts, "totalpairs")
    if raw is None:
        return None
    m = re.search(r"BoardAcrossPairs\.asp\?[^\"'<>\s]*", parse.decode(raw), re.I)
    return qboard_of(m.group(0)) if m else None


def _is_empty(raw: bytes) -> tuple[bool, parse.PairsBoard | None]:
    try:
        return False, parse.parse_boardacross_pairs(raw)
    except parse.EmptyPage:
        return True, None


def crawl_pairs(t: Tournament, fetcher: Fetcher) -> dict:
    counts = {"phases": 0, "sessions": 0, "boards": 0, "empty": 0}
    phases = _pairs_entry(t, fetcher)
    if not phases:
        raise RuntimeError(f"[{t.key}] no TotalPairs entry page lists phases "
                           f"(tried qgroupno={PAIRS_ENTRY_GROUPS})")
    _log(t, "pairs phases: " + ", ".join(
        f"g{p.code} {p.name} ({p.last_session} sessions)" for p in phases))
    for ph in phases:
        counts["phases"] += 1
        g = ph.code
        last = ph.last_session or MAX_SESSIONS
        for s in range(1, last + 1):
            first = 1
            raw = _get(fetcher, t, bap_url(t, g, s, 1), f"bap_g{g}_r{s}_b1.html",
                       counts, "board")
            empty, board = (True, None) if raw is None else _is_empty(raw)
            if empty:
                b0 = _first_board_from_totalpairs(t, fetcher, g, s, counts)
                if b0 is not None and b0 != 1:
                    first = b0
                    raw = _get(fetcher, t, bap_url(t, g, s, b0),
                               f"bap_g{g}_r{s}_b{b0}.html", counts, "board")
                    empty, board = (True, None) if raw is None else _is_empty(raw)
            if empty:
                _log(t, f"g{g} session {s}: no boards -> skipped")
                counts["empty"] += 1
                if ph.last_session is None:
                    break               # open-ended scan: first gap ends the phase
                continue
            counts["sessions"] += 1
            counts["boards"] += 1
            done = {first, 1}             # board 1 was tried already
            for href in board.board_hrefs:
                b = qboard_of(href)
                if b is None or b in done:
                    continue
                done.add(b)
                if _get(fetcher, t, bap_url(t, g, s, b), f"bap_g{g}_r{s}_b{b}.html",
                        counts, "board") is not None:
                    counts["boards"] += 1
            _log(t, f"g{g} session {s}: {len(done)} boards")
    return counts


def main(keys: list[str]) -> None:
    with Fetcher() as fetcher:
        for key in keys:
            t = TOURNAMENTS[key]
            print(f"=== crawling {t.key} ({t.site} {t.tournid}) ===", flush=True)
            try:
                counts = crawl(t, fetcher)
                print(f"=== {t.key} done: {counts} ===", flush=True)
            except Exception as e:
                print(f"=== {t.key} FAILED: {e.__class__.__name__}: {e} ===",
                      flush=True)


if __name__ == "__main__":
    keys = sys.argv[1:] or list(TOURNAMENTS)
    main(keys)
