"""Build the SQLite DB from the raw HTML cache (SPEC 5, 7.6).

Pure of network: reads only data/rawcache + the registry. `bb reparse` re-runs
this over the cache to rebuild the DB from scratch.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import parse
from crawl import cache_path
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


def store_tournament(conn: sqlite3.Connection, t: Tournament) -> dict:
    cur = conn.cursor()
    site_id = _id(cur, "INSERT OR IGNORE INTO site(code) VALUES(?)", (t.site,))
    site_id = conn.execute("SELECT id FROM site WHERE code=?", (t.site,)).fetchone()[0]
    cur.execute(
        "INSERT OR IGNORE INTO tournament"
        "(site_id, slug, tourn_code, name, series, year, asp_base_url, ingested_at)"
        " VALUES(?,?,?,?,?,?,?, datetime('now'))",
        (site_id, t.key, t.tournid, t.name, t.series, t.year, t.base),
    )
    tid = conn.execute(
        "SELECT id FROM tournament WHERE site_id=? AND tourn_code=?",
        (site_id, t.tournid),
    ).fetchone()[0]

    players = _Players(conn)
    counts = {"rounds": 0, "matches": 0, "deals": 0, "instances": 0, "auctions": 0}

    rnd = 0
    while True:
        rnd += 1
        rt_file = cache_path(t, f"roundteams_r{rnd}.html")
        if not rt_file.exists():
            break
        rt = parse.parse_roundteams(rt_file.read_bytes())
        if not rt.matches:
            break
        counts["rounds"] += 1
        round_id = _id(cur, "INSERT OR IGNORE INTO round(tournament_id, number) "
                            "VALUES(?,?)", (tid, rnd))
        round_id = conn.execute(
            "SELECT id FROM round WHERE tournament_id=? AND number=?", (tid, rnd)
        ).fetchone()[0]

        # teams
        team_ids: dict[int, int] = {}
        for m in rt.matches:
            for ext, name in ((m.home_team_id, m.home_team),
                              (m.visiting_team_id, m.visiting_team)):
                cur.execute(
                    "INSERT OR IGNORE INTO team(tournament_id, ext_id, name) "
                    "VALUES(?,?,?)", (tid, ext, name))
        for ext, tid_row in conn.execute(
            "SELECT ext_id, id FROM team WHERE tournament_id=?", (tid,)
        ):
            team_ids[ext] = tid_row

        # deals for the round (from handsacross)
        deal_ids: dict[int, int] = {}
        ha_file = cache_path(t, f"handsacross_r{rnd}.html")
        if ha_file.exists():
            for d in parse.parse_handsacross(ha_file.read_bytes()):
                did = _id(cur,
                    "INSERT OR IGNORE INTO deal(round_id, board_no, dealer, vul, "
                    "hand_n, hand_e, hand_s, hand_w, source_url) "
                    "VALUES(?,?,?,?,?,?,?,?,?)",
                    (round_id, d.board_no, d.dealer, d.vul,
                     d.hand_n, d.hand_e, d.hand_s, d.hand_w,
                     source_url(t, rnd, d.board_no)))
                deal_ids[d.board_no] = conn.execute(
                    "SELECT id FROM deal WHERE round_id=? AND board_no=?",
                    (round_id, d.board_no)).fetchone()[0]
        counts["deals"] += len(deal_ids)

        # matches + seatings + instances + auctions
        for m in rt.matches:
            match_id = _id(cur,
                "INSERT OR IGNORE INTO match(round_id, ext_match_id, "
                "home_team_id, visiting_team_id) VALUES(?,?,?,?)",
                (round_id, m.ext_match_id,
                 team_ids.get(m.home_team_id), team_ids.get(m.visiting_team_id)))
            match_id = conn.execute(
                "SELECT id FROM match WHERE round_id=? AND ext_match_id=?",
                (round_id, m.ext_match_id)).fetchone()[0]
            counts["matches"] += 1

            bd_file = cache_path(t, f"boarddetails_{m.ext_match_id}.html")
            if not bd_file.exists():
                continue
            try:
                bd = parse.parse_boarddetails(bd_file.read_bytes())
            except Exception as e:      # unrecognised page variant (SPEC 8.6)
                counts.setdefault("bad_matches", 0)
                counts["bad_matches"] += 1
                continue
            for room, seats in (("Open", bd.seating.open),
                                ("Closed", bd.seating.closed)):
                for seat, name in seats.items():
                    if not name:
                        continue
                    cur.execute(
                        "INSERT OR IGNORE INTO seating(match_id, room, seat, "
                        "player_id) VALUES(?,?,?,?)",
                        (match_id, room, seat, players.get(name)))

            for inst in bd.instances:
                deal_id = deal_ids.get(inst.board_no)
                if deal_id is None:
                    continue  # deal missing from handsacross; skip (rare)
                bi_id = _id(cur,
                    "INSERT OR IGNORE INTO board_instance(deal_id, match_id, room, "
                    "contract, declarer, lead, tricks, score_ns, score_ew) "
                    "VALUES(?,?,?,?,?,?,?,?,?)",
                    (deal_id, match_id, inst.room, inst.contract, inst.declarer,
                     inst.lead, inst.tricks, inst.score_ns, inst.score_ew))
                bi_id = conn.execute(
                    "SELECT id FROM board_instance WHERE deal_id=? AND match_id=? "
                    "AND room=?", (deal_id, match_id, inst.room)).fetchone()[0]
                counts["instances"] += 1
                calls = " ".join(inst.auction.calls)
                cur.execute(
                    "INSERT OR IGNORE INTO auction(board_instance_id, calls, complete)"
                    " VALUES(?,?,?)",
                    (bi_id, calls, int(parse.auction_complete(inst.auction.calls))))
                counts["auctions"] += 1
        conn.commit()
    conn.commit()
    return counts
