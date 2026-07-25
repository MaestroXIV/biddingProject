"""Read-only queries over boardbase.db for the browse UI (SPEC 7.1/7.2)."""
from __future__ import annotations

import sqlite3
import statistics
from pathlib import Path

SEATS = ("N", "E", "S", "W")
_HCP = {"A": 4, "K": 3, "Q": 2, "J": 1}


def _hcp(hand: str) -> int:
    return sum(_HCP.get(c, 0) for c in hand.replace(".", ""))


def _pattern(hand: str) -> str:
    lens = sorted((0 if s == "-" else len(s) for s in hand.split(".")), reverse=True)
    return "".join(map(str, lens))


def _rotate(dealer: str, steps: int) -> str:
    return SEATS[(SEATS.index(dealer) + steps) % 4]

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
    if f.get("seq", "").strip():
        seq = " ".join(f["seq"].split())
        col = "a.from_opener" if "(" in seq else "a.uncontested_key"
        add(f"{col} IS NOT NULL AND ({col} = ? OR {col} LIKE ?)", seq, seq + " %")
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


# --- sequence explorer (SPEC 7.3) -------------------------------------------

def explore(conn, f: dict, seq: str, next_hcp_min: str = "", next_hcp_max: str = ""):
    """Next-call faceting after a sequence prefix (SPEC 6, 7.3).

    A prefix without parentheses matches uncontested_key (opening side only);
    with parentheses it matches from_opener (defenders in parens). For each
    distinct *next* call we return its count, a hand summary of the player who
    made it (HCP min/median/max, common shapes), and sample boards.
    """
    seq = " ".join(seq.split())
    seq_tokens = seq.split() if seq else []
    depth = len(seq_tokens)
    contested = "(" in seq
    key_col = "a.from_opener" if contested else "a.uncontested_key"
    stride = 1 if contested else 2   # from_opener: every call; uncontested: opener side only

    where, params = build_filters(conn, {**f, "seq": ""})  # apply all but seq here
    clause = f"{key_col} IS NOT NULL"
    if seq:
        clause += f" AND ({key_col} = ? OR {key_col} LIKE ?)"
    prefix_params = ([seq, seq + " %"] if seq else [])
    full_where = (where + (" AND " if where else " WHERE ") + clause)

    sql = f"""
    SELECT {key_col} AS key, a.opener_rel_pos AS orp, d.dealer AS dealer,
           d.hand_n, d.hand_e, d.hand_s, d.hand_w,
           bi.id AS bi_id, d.id AS deal_id, d.board_no, r.number AS round_no,
           t.slug AS tslug
    {BASE}{full_where}"""
    rows = conn.execute(sql, params + prefix_params).fetchall()

    hmin = int(next_hcp_min) if str(next_hcp_min).strip() else None
    hmax = int(next_hcp_max) if str(next_hcp_max).strip() else None

    branches: dict[str, dict] = {}
    matched = 0
    ended = 0
    for r in rows:
        toks = r["key"].split()
        if toks[:depth] != seq_tokens:
            continue
        matched += 1
        if len(toks) <= depth:
            ended += 1
            continue
        nxt = toks[depth]
        # seat that made the next call
        abs_idx = (r["orp"] - 1) + stride * depth
        seat = _rotate(r["dealer"], abs_idx)
        hand = {"N": r["hand_n"], "E": r["hand_e"],
                "S": r["hand_s"], "W": r["hand_w"]}[seat]
        h = _hcp(hand)
        if (hmin is not None and h < hmin) or (hmax is not None and h > hmax):
            continue
        b = branches.setdefault(nxt, {"call": nxt, "count": 0, "hcps": [],
                                      "patterns": {}, "samples": []})
        b["count"] += 1
        b["hcps"].append(h)
        b["patterns"][_pattern(hand)] = b["patterns"].get(_pattern(hand), 0) + 1
        if len(b["samples"]) < 6:
            b["samples"].append({"deal_id": r["deal_id"], "tslug": r["tslug"],
                                 "round_no": r["round_no"], "board_no": r["board_no"],
                                 "seat": seat, "hand": hand, "hcp": h})

    out = []
    for b in branches.values():
        hcps = b["hcps"]
        pats = sorted(b["patterns"].items(), key=lambda kv: -kv[1])[:3]
        out.append({
            "call": b["call"], "count": b["count"],
            "hcp_min": min(hcps), "hcp_med": round(statistics.median(hcps)),
            "hcp_max": max(hcps),
            "patterns": [f"{p}×{n}" for p, n in pats],
            "samples": b["samples"],
        })
    out.sort(key=lambda x: -x["count"])
    filtered = (hmin is not None or hmax is not None)
    facet_total = sum(b["count"] for b in out) if filtered else (matched - ended)
    return {"seq": seq, "seq_tokens": seq_tokens, "contested": contested,
            "matched": matched, "ended": ended, "facet_total": facet_total,
            "branches": out}


# --- pair / player dashboards (SPEC 7.4) ------------------------------------

def resolve_one_player(conn, name: str):
    """Best single (id, canonical_name) for a name; prefers an exact alias."""
    if not name.strip():
        return None
    row = conn.execute(
        "SELECT p.id, p.canonical_name FROM player p JOIN player_alias a "
        "ON a.player_id=p.id WHERE a.alias=? LIMIT 1", (name.strip(),)).fetchone()
    if row:
        return row["id"], row["canonical_name"]
    row = conn.execute(
        "SELECT p.id, p.canonical_name FROM player p JOIN player_alias a "
        "ON a.player_id=p.id WHERE a.alias LIKE ? ORDER BY length(a.alias) LIMIT 1",
        (f"%{name.strip()}%",)).fetchone()
    return (row["id"], row["canonical_name"]) if row else None


_POS = (1, 2, 3, 4)
_VULS = ("none", "fav", "unfav", "both")


def opening_grid(conn, opener_ids: list[int], pair_key: str | None = None,
                 tournament: str = ""):
    """Opening-call frequency split by position, vulnerability, and (for a pair)
    which member opened. Returns rows sorted by total desc."""
    joins = ("JOIN board_instance bi ON bi.id=a.board_instance_id "
             "JOIN match m ON m.id=bi.match_id JOIN round r ON r.id=m.round_id "
             "JOIN tournament t ON t.id=r.tournament_id")
    conds = ["a.opening_call IS NOT NULL",
             f"a.opener_player_id IN ({','.join('?'*len(opener_ids))})"]
    params: list = list(opener_ids)
    if pair_key:
        joins += (" JOIN instance_side s ON s.board_instance_id=a.board_instance_id "
                  "AND s.side=a.opening_side")
        conds.append("s.pair_key=?")
        params.append(pair_key)
    if tournament:
        conds.append("t.slug=?")
        params.append(tournament)
    sql = (f"SELECT a.opening_call AS call, a.opener_player_id AS pid, "
           f"a.opener_rel_pos AS pos, a.vul_rel AS vul, COUNT(*) AS n "
           f"FROM auction a {joins} WHERE {' AND '.join(conds)} "
           f"GROUP BY call, pid, pos, vul")
    grid: dict[str, dict] = {}
    for r in conn.execute(sql, params):
        g = grid.setdefault(r["call"], {
            "call": r["call"], "total": 0,
            "by_pos": {p: 0 for p in _POS}, "by_vul": {v: 0 for v in _VULS},
            "by_player": {}})
        g["total"] += r["n"]
        g["by_pos"][r["pos"]] = g["by_pos"].get(r["pos"], 0) + r["n"]
        if r["vul"]:
            g["by_vul"][r["vul"]] = g["by_vul"].get(r["vul"], 0) + r["n"]
        g["by_player"][r["pid"]] = g["by_player"].get(r["pid"], 0) + r["n"]
    rows = sorted(grid.values(), key=lambda g: -g["total"])
    return rows


def player_events(conn, player_id: int):
    return conn.execute("""
        SELECT DISTINCT t.slug, t.name FROM seating se
        JOIN match m ON m.id=se.match_id JOIN round r ON r.id=m.round_id
        JOIN tournament t ON t.id=r.tournament_id WHERE se.player_id=?
        ORDER BY t.id""", (player_id,)).fetchall()


def player_partners(conn, player_id: int, tournament: str = ""):
    cond = "(s.player_lo=? OR s.player_hi=?)"
    params: list = [player_id, player_id]
    join = ("JOIN board_instance bi ON bi.id=s.board_instance_id "
            "JOIN match m ON m.id=bi.match_id JOIN round r ON r.id=m.round_id "
            "JOIN tournament t ON t.id=r.tournament_id")
    if tournament:
        cond += " AND t.slug=?"
        params.append(tournament)
    rows = conn.execute(f"""
        SELECT CASE WHEN s.player_lo=? THEN s.player_hi ELSE s.player_lo END AS partner,
               COUNT(*) AS n
        FROM instance_side s {join} WHERE {cond}
        GROUP BY partner ORDER BY n DESC""",
        [player_id] + params).fetchall()
    out = []
    for r in rows:
        nm = conn.execute("SELECT canonical_name FROM player WHERE id=?",
                          (r["partner"],)).fetchone()
        out.append({"id": r["partner"], "name": nm["canonical_name"] if nm else "?",
                    "n": r["n"]})
    return out


def player_name(conn, player_id: int):
    r = conn.execute("SELECT canonical_name FROM player WHERE id=?",
                     (player_id,)).fetchone()
    return r["canonical_name"] if r else None


def pair_key_for(a_id: int, b_id: int) -> str:
    lo, hi = sorted((a_id, b_id))
    return f"{lo}-{hi}"
