"""Recompute derived tables from the DB alone (SPEC 5 'derived rows').

No network, no cache: reads deal/board_instance/auction/seating and fills the
auction derived columns, hand_feature, and instance_side. Idempotent.
"""
from __future__ import annotations

import sqlite3

import bridge
from bridge import SIDE, is_bid, rotate_from


def _vul_rel(vul: str, opening_side: str) -> str:
    other = "EW" if opening_side == "NS" else "NS"
    open_vul = vul == "ALL" or vul == opening_side
    opp_vul = vul == "ALL" or vul == other
    if open_vul and opp_vul:
        return "both"
    if not open_vul and not opp_vul:
        return "none"
    return "fav" if opp_vul else "unfav"


def _canonical(calls: list[str], dealer: str, opener_idx: int, opening_side: str):
    """Return (from_opener, uncontested_key|None, competitive)."""
    from_tokens: list[str] = []
    unc_tokens: list[str] = []
    competitive = False
    for k in range(opener_idx, len(calls)):
        seat = rotate_from(dealer, k)
        call = calls[k]
        if SIDE[seat] == opening_side:
            from_tokens.append(call)
            unc_tokens.append(call)
        else:
            from_tokens.append(f"({call})")
            if call != "P":
                competitive = True
    unc = None if competitive else " ".join(unc_tokens)
    return " ".join(from_tokens), unc, int(competitive)


def derive(conn: sqlite3.Connection) -> dict:
    cur = conn.cursor()
    counts = {"auctions": 0, "hand_features": 0, "instance_sides": 0}

    # --- hand_feature -------------------------------------------------------
    cur.execute("DELETE FROM hand_feature")
    for deal_id, hn, he, hs, hw in conn.execute(
        "SELECT id, hand_n, hand_e, hand_s, hand_w FROM deal"
    ).fetchall():
        for seat, hand in (("N", hn), ("E", he), ("S", hs), ("W", hw)):
            cur.execute(
                "INSERT INTO hand_feature(deal_id, seat, hcp, shape, pattern, "
                "balanced, longest_suit) VALUES(?,?,?,?,?,?,?)",
                (deal_id, seat, bridge.hcp(hand), bridge.shape(hand),
                 bridge.pattern(hand), int(bridge.is_balanced(hand)),
                 bridge.longest_suit(hand)))
            counts["hand_features"] += 1

    # --- instance_side (pairs per side) ------------------------------------
    cur.execute("DELETE FROM instance_side")
    for bi_id, match_id, room in conn.execute(
        "SELECT id, match_id, room FROM board_instance"
    ).fetchall():
        seat_player = dict(conn.execute(
            "SELECT seat, player_id FROM seating WHERE match_id=? AND room=?",
            (match_id, room)))
        for side, seats in (("NS", ("N", "S")), ("EW", ("E", "W"))):
            a, b = seat_player.get(seats[0]), seat_player.get(seats[1])
            if a is None or b is None:
                continue
            lo, hi = sorted((a, b))
            cur.execute(
                "INSERT INTO instance_side(board_instance_id, side, player_lo, "
                "player_hi, pair_key) VALUES(?,?,?,?,?)",
                (bi_id, side, lo, hi, f"{lo}-{hi}"))
            counts["instance_sides"] += 1

    # --- auction derived columns -------------------------------------------
    rows = conn.execute(
        "SELECT a.board_instance_id, a.calls, d.dealer, d.vul, bi.match_id, bi.room "
        "FROM auction a JOIN board_instance bi ON bi.id=a.board_instance_id "
        "JOIN deal d ON d.id=bi.deal_id"
    ).fetchall()
    for bi_id, calls_str, dealer, vul, match_id, room in rows:
        calls = calls_str.split() if calls_str else []
        opener_idx = next((i for i, c in enumerate(calls) if is_bid(c)), None)
        if opener_idx is None:
            cur.execute(
                "UPDATE auction SET competitive=0, uncontested_key=NULL "
                "WHERE board_instance_id=?", (bi_id,))
            counts["auctions"] += 1
            continue
        opener_seat = rotate_from(dealer, opener_idx)
        opening_side = SIDE[opener_seat]
        opening_call = calls[opener_idx]
        opener_pid = conn.execute(
            "SELECT player_id FROM seating WHERE match_id=? AND room=? AND seat=?",
            (match_id, room, opener_seat)).fetchone()
        opener_pid = opener_pid[0] if opener_pid else None
        from_opener, unc, competitive = _canonical(
            calls, dealer, opener_idx, opening_side)
        cur.execute(
            "UPDATE auction SET opener_seat=?, opener_rel_pos=?, opening_call=?, "
            "opener_player_id=?, opening_side=?, competitive=?, vul_rel=?, "
            "from_opener=?, uncontested_key=? WHERE board_instance_id=?",
            (opener_seat, opener_idx + 1, opening_call, opener_pid, opening_side,
             competitive, _vul_rel(vul, opening_side), from_opener, unc, bi_id))
        counts["auctions"] += 1
    conn.commit()
    return counts
