"""Build the SQLite DB from the raw HTML cache (SPEC 5, 7.6).

Pure of network: reads only data/rawcache + the registry. `bb reparse` re-runs
this over the cache to rebuild the DB from scratch.
"""
from __future__ import annotations

import re
import sqlite3
import zlib
from pathlib import Path

import parse
from crawl import cache_dir, cache_path
from registry import Tournament

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "data" / "boardbase.db"
SCHEMA = REPO_ROOT / "db" / "schema.sql"


# Columns added after v1 (PAIRS_KO.md). CREATE TABLE IF NOT EXISTS never alters
# an existing DB, so add any that are missing -- old DBs upgrade in place.
_MIGRATIONS = {
    "tournament": [("kind", "TEXT DEFAULT 'teams'")],
    "round": [("stage", "TEXT")],
    "match": [("seats_known", "INT DEFAULT 1")],
    "board_instance": [("mp_ns", "REAL"), ("mp_ew", "REAL"), ("pct_ns", "REAL"),
                       ("pct_ew", "REAL"), ("table_label", "TEXT")],
}


def migrate(conn: sqlite3.Connection) -> None:
    for table, cols in _MIGRATIONS.items():
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, decl in cols:
            if name not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
    conn.commit()


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA.read_text())
    migrate(conn)
    return conn


def _id(cur, sql: str, params: tuple) -> int:
    cur.execute(sql, params)
    return cur.lastrowid


class _Players:
    """Alias -> canonical player id, created on first sight (SPEC 5)."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.cache: dict[str, int] = {}
        for alias, pid in conn.execute(
            "SELECT alias, player_id FROM player_alias"
        ):
            self.cache[alias] = pid

    def get(self, alias: str, country: str = "") -> int:
        alias = alias.strip()
        if alias in self.cache:
            return self.cache[alias]
        cur = self.conn.cursor()
        pid = _id(cur, "INSERT INTO player(canonical_name, country) VALUES(?,?)",
                  (alias, country))
        cur.execute("INSERT INTO player_alias(alias, player_id) VALUES(?,?)",
                    (alias, pid))
        self.cache[alias] = pid
        return pid




def source_url(t: Tournament, round_no: int, board_no: int) -> str:
    return (f"{t.base}BoardAcross.asp?"
            f"qboard={board_no:03d}.{round_no:02d}..{t.tournid}")


def ko_source_url(t: Tournament, phase: str, segment: int, board_no: int) -> str:
    return (f"{t.base}BoardAcrossKO.asp?"
            f"qboard={board_no:03d}.{segment:02d}.{phase}.{t.tournid}")


def pairs_source_url(t: Tournament, group: str, session: int, board_no: int) -> str:
    return (f"{t.base}BoardAcrossPairs.asp?qboard={board_no}&qtournid={t.tournid}"
            f"&qroundno={session}&qgroupno={group}")


def ko_team_ext_id(name: str) -> int:
    """KO pages carry no team id: a stable synthetic (negative) one from the name."""
    return -(zlib.crc32(name.encode("utf-8")) & 0x7FFFFFFF)


def ko_stage(phase_name: str) -> str:
    """'Mixed Teams - Phase of 16' -> 'Phase of 16'."""
    return phase_name.rsplit(" - ", 1)[-1].strip()


def _surname(player: str) -> str:
    """'VAN DER NEUT Jaap' -> 'VAN DER NEUT'; falls back to the first word."""
    words = player.split()
    caps = []
    for w in words:
        if any(ch.isalpha() for ch in w) and w == w.upper():
            caps.append(w)
        else:
            break
    return " ".join(caps) if caps else (words[0] if words else "")


def pair_name(players: list[str]) -> str:
    return " – ".join(_surname(p) for p in players if p.strip())


# --- shared row helpers (INSERT OR IGNORE + reselect: idempotent) -------------

class _Writer:
    def __init__(self, conn: sqlite3.Connection, t: Tournament):
        self.conn, self.t = conn, t
        self.cur = conn.cursor()
        self.players = _Players(conn)
        self.counts = {"rounds": 0, "matches": 0, "deals": 0, "instances": 0,
                       "auctions": 0}
        self.tid = self._tournament()

    def one(self, sql: str, params: tuple):
        return self.conn.execute(sql, params).fetchone()[0]

    def _tournament(self) -> int:
        t, cur = self.t, self.cur
        cur.execute("INSERT OR IGNORE INTO site(code) VALUES(?)", (t.site,))
        site_id = self.one("SELECT id FROM site WHERE code=?", (t.site,))
        cur.execute(
            "INSERT OR IGNORE INTO tournament"
            "(site_id, slug, tourn_code, name, series, year, asp_base_url, "
            "ingested_at, kind) VALUES(?,?,?,?,?,?,?, datetime('now'), ?)",
            (site_id, t.key, t.tournid, t.name, t.series, t.year, t.base, t.kind),
        )
        tid = self.one("SELECT id FROM tournament WHERE site_id=? AND tourn_code=?",
                       (site_id, t.tournid))
        cur.execute("UPDATE tournament SET kind=? WHERE id=? AND "
                    "(kind IS NULL OR kind<>?)", (t.kind, tid, t.kind))
        return tid

    def round(self, number: int, label: str | None = None,
              stage: str | None = None) -> int:
        self.cur.execute("INSERT OR IGNORE INTO round(tournament_id, number, label, "
                         "stage) VALUES(?,?,?,?)", (self.tid, number, label, stage))
        rid = self.one("SELECT id FROM round WHERE tournament_id=? AND number=?",
                       (self.tid, number))
        if label is not None or stage is not None:
            self.cur.execute("UPDATE round SET label=?, stage=? WHERE id=?",
                             (label, stage, rid))
        self.counts["rounds"] += 1
        return rid

    def team(self, ext_id: int | None, name: str) -> int | None:
        self.cur.execute("INSERT OR IGNORE INTO team(tournament_id, ext_id, name) "
                         "VALUES(?,?,?)", (self.tid, ext_id, name))
        if ext_id is None:
            return None
        return self.one("SELECT id FROM team WHERE tournament_id=? AND ext_id=?",
                        (self.tid, ext_id))

    def deal(self, round_id: int, d: parse.Deal, url: str) -> int:
        self.cur.execute(
            "INSERT OR IGNORE INTO deal(round_id, board_no, dealer, vul, "
            "hand_n, hand_e, hand_s, hand_w, source_url) VALUES(?,?,?,?,?,?,?,?,?)",
            (round_id, d.board_no, d.dealer, d.vul,
             d.hand_n, d.hand_e, d.hand_s, d.hand_w, url))
        return self.one("SELECT id FROM deal WHERE round_id=? AND board_no=?",
                        (round_id, d.board_no))

    def match(self, round_id: int, ext_match_id: int, home: int | None,
              visiting: int | None, seats_known: int = 1) -> int:
        self.cur.execute(
            "INSERT OR IGNORE INTO match(round_id, ext_match_id, home_team_id, "
            "visiting_team_id, seats_known) VALUES(?,?,?,?,?)",
            (round_id, ext_match_id, home, visiting, seats_known))
        mid = self.one("SELECT id FROM match WHERE round_id=? AND ext_match_id=?",
                       (round_id, ext_match_id))
        if seats_known != 1:
            self.cur.execute("UPDATE match SET seats_known=? WHERE id=?",
                             (seats_known, mid))
        return mid

    def seat(self, match_id: int, room: str, seat: str, name: str) -> None:
        if not name or not name.strip():
            return
        self.cur.execute(
            "INSERT OR IGNORE INTO seating(match_id, room, seat, player_id) "
            "VALUES(?,?,?,?)", (match_id, room, seat, self.players.get(name)))

    def instance(self, deal_id: int, match_id: int, room: str, contract: str,
                 declarer: str, lead: str, tricks, score_ns, score_ew,
                 auction: parse.Auction | None, mp_ns=None, mp_ew=None,
                 pct_ns=None, pct_ew=None, table_label=None) -> int:
        self.cur.execute(
            "INSERT OR IGNORE INTO board_instance(deal_id, match_id, room, "
            "contract, declarer, lead, tricks, score_ns, score_ew, "
            "mp_ns, mp_ew, pct_ns, pct_ew, table_label) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (deal_id, match_id, room, contract, declarer, lead, tricks,
             score_ns, score_ew, mp_ns, mp_ew, pct_ns, pct_ew, table_label))
        bi_id = self.one("SELECT id FROM board_instance WHERE deal_id=? AND "
                         "match_id=? AND room=?", (deal_id, match_id, room))
        self.counts["instances"] += 1
        if auction is not None:
            self.cur.execute(
                "INSERT OR IGNORE INTO auction(board_instance_id, calls, complete)"
                " VALUES(?,?,?)",
                (bi_id, " ".join(auction.calls),
                 int(parse.auction_complete(auction.calls))))
            self.counts["auctions"] += 1
        return bi_id

    def bad(self, what: str = "bad_matches") -> None:
        self.counts[what] = self.counts.get(what, 0) + 1

    def boarddetails(self, match_id: int, bd: parse.BoardDetails,
                     deal_ids: dict[int, int]) -> None:
        """Seating + instances + auctions of one teams/KO match page."""
        for room, seats in (("Open", bd.seating.open), ("Closed", bd.seating.closed)):
            for seat, name in seats.items():
                self.seat(match_id, room, seat, name)
        for inst in bd.instances:
            deal_id = deal_ids.get(inst.board_no)
            if deal_id is None:
                continue  # deal missing from handsacross; skip (rare)
            self.instance(deal_id, match_id, inst.room, inst.contract,
                          inst.declarer, inst.lead, inst.tricks,
                          inst.score_ns, inst.score_ew, inst.auction)


def store_tournament(conn: sqlite3.Connection, t: Tournament) -> dict:
    w = _Writer(conn, t)
    if t.kind == "ko":
        _store_ko(w)
    elif t.kind == "pairs":
        _store_pairs(w)
    else:
        _store_teams(w)
    conn.commit()
    return w.counts


# --- teams -------------------------------------------------------------------

def _store_teams(w: _Writer) -> None:
    t, conn = w.t, w.conn
    rnd = 0
    while True:
        rnd += 1
        rt_file = cache_path(t, f"roundteams_r{rnd}.html")
        if not rt_file.exists():
            break
        rt = parse.parse_roundteams(rt_file.read_bytes())
        if not rt.matches:
            break
        round_id = w.round(rnd)

        team_ids: dict[int, int] = {}
        for m in rt.matches:
            w.team(m.home_team_id, m.home_team)
            w.team(m.visiting_team_id, m.visiting_team)
        for ext, tid_row in conn.execute(
                "SELECT ext_id, id FROM team WHERE tournament_id=?", (w.tid,)):
            team_ids[ext] = tid_row

        deal_ids: dict[int, int] = {}
        ha_file = cache_path(t, f"handsacross_r{rnd}.html")
        if ha_file.exists():
            for d in parse.parse_handsacross(ha_file.read_bytes()):
                deal_ids[d.board_no] = w.deal(round_id, d,
                                              source_url(t, rnd, d.board_no))
        w.counts["deals"] += len(deal_ids)

        for m in rt.matches:
            match_id = w.match(round_id, m.ext_match_id,
                               team_ids.get(m.home_team_id),
                               team_ids.get(m.visiting_team_id))
            w.counts["matches"] += 1
            bd_file = cache_path(t, f"boarddetails_{m.ext_match_id}.html")
            if not bd_file.exists():
                continue
            try:
                bd = parse.parse_boarddetails(bd_file.read_bytes())
            except Exception:           # unrecognised page variant (SPEC 8.6)
                w.bad()
                continue
            w.boarddetails(match_id, bd, deal_ids)
        conn.commit()


# --- knockout ----------------------------------------------------------------

def _store_ko(w: _Writer) -> None:
    t = w.t
    entry = cache_path(t, "ko_entry.html")
    if not entry.exists():
        return
    phases = parse.parse_ko_phases(entry.read_bytes(), t.tournid)
    for pi, ph in enumerate(phases, start=1):
        ph_file = cache_path(t, f"ko_phase_{ph.code}.html")
        if not ph_file.exists():
            continue
        stage = ko_stage(ph.name)
        # group the phase's match pages by segment
        by_seg: dict[int, list[tuple[int, parse.BoardDetails]]] = {}
        for mid in parse.parse_ko_match_ids(ph_file.read_bytes()):
            f = cache_path(t, f"bdko_{mid}.html")
            if not f.exists():
                continue
            try:
                bd = parse.parse_boarddetails(f.read_bytes())
            except Exception:
                w.bad()
                continue
            if bd.segment is None:
                w.bad()
                continue
            by_seg.setdefault(bd.segment, []).append((mid, bd))

        for seg in sorted(by_seg):
            round_id = w.round(pi * 100 + seg, f"{stage} · Seg {seg}", stage)
            deal_ids: dict[int, int] = {}
            ha = cache_path(t, f"hako_{ph.code}_r{seg}.html")
            if ha.exists():
                for d in parse.parse_handsacross(ha.read_bytes()):
                    deal_ids[d.board_no] = w.deal(
                        round_id, d, ko_source_url(t, ph.code, seg, d.board_no))
            w.counts["deals"] += len(deal_ids)
            for mid, bd in by_seg[seg]:
                home = w.team(ko_team_ext_id(bd.home_team), bd.home_team)
                vis = w.team(ko_team_ext_id(bd.visiting_team), bd.visiting_team)
                match_id = w.match(round_id, mid, home, vis)
                w.counts["matches"] += 1
                w.boarddetails(match_id, bd, deal_ids)
            w.conn.commit()


# --- pairs -------------------------------------------------------------------

_BAP = re.compile(r"^bap_g(\w+?)_r(\d+)_b(\d+)\.html$")


def _cached_pairs_boards(t: Tournament) -> dict[tuple[str, int], list[tuple[int, Path]]]:
    """{(group, session): [(board, path), ...]} from the cache, boards sorted."""
    out: dict[tuple[str, int], list[tuple[int, Path]]] = {}
    d = cache_dir(t)
    if not d.exists():
        return out
    for p in d.iterdir():
        m = _BAP.match(p.name)
        if m:
            out.setdefault((m.group(1), int(m.group(2))), []).append(
                (int(m.group(3)), p))
    for v in out.values():
        v.sort()
    return out


def _table_label(tb: parse.PairsTable) -> str | None:
    parts = [tb.section.strip()] if tb.section and tb.section.strip() else []
    if tb.table_no is not None:
        parts.append(f"Tbl {tb.table_no}")
    return " ".join(parts) or None


def _store_pairs(w: _Writer) -> None:
    t = w.t
    entry = cache_path(t, "tp_entry.html")
    if not entry.exists():
        return
    phases = parse.parse_pairs_phases(entry.read_bytes(), t.tournid)
    cached = _cached_pairs_boards(t)
    for pi, ph in enumerate(phases, start=1):
        sessions = sorted(s for (g, s) in cached if g == str(ph.code))
        for s in sessions:
            boards = []
            for _b, path in cached[(str(ph.code), s)]:
                try:
                    boards.append(parse.parse_boardacross_pairs(path.read_bytes()))
                except parse.EmptyPage:
                    continue
                except Exception:
                    w.bad("bad_boards")
                    continue
            if not boards:
                continue                        # missing session
            round_id = w.round(pi * 100 + s, f"{ph.name} · Session {s}", ph.name)
            for pb in boards:
                bno = pb.deal.board_no
                deal_id = w.deal(round_id, pb.deal,
                                 pairs_source_url(t, ph.code, s, bno))
                w.counts["deals"] += 1
                for tb in pb.tables:
                    ns = w.team(tb.ns_pair_id, pair_name(tb.ns_players))
                    ew = w.team(tb.ew_pair_id, pair_name(tb.ew_players))
                    ext = tb.ns_pair_id * 100000 + tb.ew_pair_id
                    new = w.conn.execute(
                        "SELECT 1 FROM match WHERE round_id=? AND ext_match_id=?",
                        (round_id, ext)).fetchone() is None
                    match_id = w.match(round_id, ext, ns, ew, seats_known=0)
                    if new:
                        w.counts["matches"] += 1
                    # synthetic seating: order as listed, NOT real seats
                    for seat, players, i in (("N", tb.ns_players, 0),
                                             ("S", tb.ns_players, 1),
                                             ("E", tb.ew_players, 0),
                                             ("W", tb.ew_players, 1)):
                        if i < len(players):
                            w.seat(match_id, "Open", seat, players[i])
                    w.instance(deal_id, match_id, "Open", tb.contract, tb.declarer,
                               tb.lead, tb.tricks, tb.score_ns, tb.score_ew,
                               tb.auction, tb.mp_ns, tb.mp_ew, tb.pct_ns,
                               tb.pct_ew, _table_label(tb))
            w.conn.commit()
