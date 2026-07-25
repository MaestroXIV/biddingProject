"""Read-only queries over boardbase.db for the browse UI (SPEC 7.1/7.2)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "boardbase.db"

_SEAT_HAND = {"N": "hand_n", "E": "hand_e", "S": "hand_s", "W": "hand_w"}


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _resolve_player_ids(conn, name: str) -> list[int]:
    if not name.strip():
        return []
    rows = conn.execute(
        "SELECT DISTINCT player_id FROM player_alias WHERE alias LIKE ?",
        (f"%{name.strip()}%",)).fetchall()
    return [r[0] for r in rows]


# --- dropdown data ----------------------------------------------------------

def tournaments(conn):
    return conn.execute(
        "SELECT slug, name FROM tournament ORDER BY id").fetchall()


def opening_calls(conn):
    return [r[0] for r in conn.execute(
        "SELECT DISTINCT opening_call FROM auction WHERE opening_call IS NOT NULL "
        "ORDER BY length(opening_call), opening_call")]


# --- search (home) ----------------------------------------------------------

BASE = """
FROM board_instance bi
JOIN deal d      ON d.id = bi.deal_id
JOIN round r     ON r.id = d.round_id
JOIN tournament t ON t.id = r.tournament_id
JOIN match m     ON m.id = bi.match_id
LEFT JOIN auction a ON a.board_instance_id = bi.id
LEFT JOIN team ht ON ht.id = m.home_team_id
LEFT JOIN team vt ON vt.id = m.visiting_team_id
"""


def build_filters(conn, f: dict):
    where, params = [], []

    def add(clause, *ps):
        where.append(clause)
        params.extend(ps)

    if f.get("tournament"):
        add("t.slug = ?", f["tournament"])
    if f.get("opening_call"):
        add("a.opening_call = ?", f["opening_call"])
    if f.get("dealer"):
        add("d.dealer = ?", f["dealer"])
    if f.get("vul"):
        add("d.vul = ?", f["vul"])
    if f.get("declarer"):
        add("bi.declarer = ?", f["declarer"])
    if f.get("contract"):
        add("bi.contract = ?", f["contract"].upper())
    if f.get("position"):
        add("a.opener_rel_pos = ?", int(f["position"]))
    if f.get("competitive") in ("0", "1"):
        add("a.competitive = ?", int(f["competitive"]))
    if f.get("round_from"):
        add("r.number >= ?", int(f["round_from"]))
    if f.get("round_to"):
        add("r.number <= ?", int(f["round_to"]))

    # player: any seat, or opener only
    pids = _resolve_player_ids(conn, f.get("player", ""))
    if f.get("player", "").strip():
        if not pids:
            add("1 = 0")  # no such player -> empty result
        elif f.get("player_role") == "opener":
            add(f"a.opener_player_id IN ({','.join('?'*len(pids))})", *pids)
        else:
            add("EXISTS (SELECT 1 FROM seating s WHERE s.match_id=bi.match_id "
                f"AND s.room=bi.room AND s.player_id IN ({','.join('?'*len(pids))}))",
                *pids)

    # pair: player + partner on the opening side (use-case 1)
    partner = f.get("partner", "").strip()
    if partner:
        ppids = _resolve_player_ids(conn, partner)
        if pids and ppids:
            # match any (player, partner) id combination as an unordered pair
            keys = {f"{lo}-{hi}" for a1 in pids for b1 in ppids
                    for lo, hi in [sorted((a1, b1))] if a1 != b1}
            if keys:
                side = "a.opening_side" if f.get("pair_side") == "opening" else "side"
                placeholders = ",".join("?" * len(keys))
                add(f"EXISTS (SELECT 1 FROM instance_side si WHERE "
                    f"si.board_instance_id=bi.id AND si.pair_key IN ({placeholders})"
                    + (f" AND si.side={side}" if f.get('pair_side')=='opening' else "")
                    + ")", *keys)
            else:
                add("1 = 0")
        else:
            add("1 = 0")

    return (" WHERE " + " AND ".join(where)) if where else "", params


def search(conn, f: dict, limit: int = 50, offset: int = 0):
    where, params = build_filters(conn, f)
    total = conn.execute(f"SELECT COUNT(*) {BASE}{where}", params).fetchone()[0]
    sql = f"""
    SELECT bi.id AS bi_id, d.id AS deal_id, t.slug AS tslug, t.name AS tname,
           r.number AS round_no, d.board_no, d.dealer, d.vul,
           d.hand_n, d.hand_e, d.hand_s, d.hand_w, d.source_url,
           bi.room, bi.contract, bi.declarer, bi.tricks, bi.score_ns, bi.score_ew,
           ht.name AS home_team, vt.name AS visiting_team, m.ext_match_id,
           a.calls, a.from_opener, a.opening_call, a.opener_seat,
           a.opener_rel_pos, a.competitive
    {BASE}{where}
    ORDER BY t.id, r.number, d.board_no, bi.room
    LIMIT ? OFFSET ?"""
    rows = conn.execute(sql, params + [limit, offset]).fetchall()
    return total, [_augment(row) for row in rows]


def _augment(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["calls_list"] = row["calls"].split() if row["calls"] else []
    seat = row["opener_seat"]
    d["opener_hand"] = row[_SEAT_HAND[seat]] if seat in _SEAT_HAND else None
    return d


# --- deal traveller ---------------------------------------------------------

def deal_header(conn, deal_id: int):
    return conn.execute("""
        SELECT d.*, r.number AS round_no, t.slug AS tslug, t.name AS tname,
               t.asp_base_url
        FROM deal d JOIN round r ON r.id=d.round_id
        JOIN tournament t ON t.id=r.tournament_id WHERE d.id=?""",
        (deal_id,)).fetchone()


def deal_instances(conn, deal_id: int, opening_call: str = ""):
    where = "WHERE bi.deal_id = ?"
    params: list = [deal_id]
    if opening_call:
        where += " AND a.opening_call = ?"
        params.append(opening_call)
    return conn.execute(f"""
        SELECT bi.id AS bi_id, bi.room, bi.contract, bi.declarer, bi.tricks,
               bi.score_ns, bi.score_ew, m.ext_match_id, m.id AS match_id,
               ht.name AS home_team, vt.name AS visiting_team,
               a.calls, a.opening_call, a.opener_seat, a.opener_rel_pos,
               ns.player_lo, r.number AS round_no
        FROM board_instance bi
        JOIN match m ON m.id=bi.match_id
        JOIN round r ON r.id=m.round_id
        LEFT JOIN auction a ON a.board_instance_id=bi.id
        LEFT JOIN team ht ON ht.id=m.home_team_id
        LEFT JOIN team vt ON vt.id=m.visiting_team_id
        LEFT JOIN instance_side ns ON ns.board_instance_id=bi.id AND ns.side='NS'
        {where}
        ORDER BY m.ext_match_id, bi.room""", params).fetchall()


def deal_opening_calls(conn, deal_id: int):
    return [r[0] for r in conn.execute(
        "SELECT DISTINCT a.opening_call FROM auction a "
        "JOIN board_instance bi ON bi.id=a.board_instance_id "
        "WHERE bi.deal_id=? AND a.opening_call IS NOT NULL "
        "ORDER BY length(a.opening_call), a.opening_call", (deal_id,))]


def players_at(conn, match_id: int, room: str) -> dict:
    return {r["seat"]: r["name"] for r in conn.execute(
        "SELECT s.seat, p.canonical_name AS name FROM seating s "
        "JOIN player p ON p.id=s.player_id WHERE s.match_id=? AND s.room=?",
        (match_id, room))}
