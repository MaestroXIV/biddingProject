"""Integrity checks (SPEC 9 M1 DoD): 52 cards/deal, auctions start at the
dealer, instance<->seating consistency. Returns a list of human-readable
problems (empty = all good)."""
from __future__ import annotations

import sqlite3

from bridge import SIDE, is_bid, rotate_from


def check(conn: sqlite3.Connection) -> list[str]:
    problems: list[str] = []

    # 52 distinct cards per deal
    bad_deals = 0
    for did, hn, he, hs, hw in conn.execute(
        "SELECT id, hand_n, hand_e, hand_s, hand_w FROM deal"
    ):
        cards = []
        for suit_i, hand in enumerate((hn, he, hs, hw)):
            for si, s in enumerate(hand.split(".")):
                if s != "-":
                    cards.extend(f"{si}{c}" for c in s)
        if len(cards) != 52 or len(set(cards)) != 52:
            bad_deals += 1
    if bad_deals:
        problems.append(f"{bad_deals} deals not a valid 52-card layout")

    # auction opener side matches the derived opening_side (dealer-first sanity)
    bad_open = 0
    for calls, dealer, opening_side, opener_seat in conn.execute(
        "SELECT a.calls, d.dealer, a.opening_side, a.opener_seat FROM auction a "
        "JOIN board_instance bi ON bi.id=a.board_instance_id "
        "JOIN deal d ON d.id=bi.deal_id WHERE a.opening_call IS NOT NULL"
    ):
        toks = calls.split()
        i = next((k for k, c in enumerate(toks) if is_bid(c)), None)
        if i is None:
            continue
        if rotate_from(dealer, i) != opener_seat or SIDE[opener_seat] != opening_side:
            bad_open += 1
    if bad_open:
        problems.append(f"{bad_open} auctions with inconsistent opener/dealer")

    # every board_instance's match+room has all four seats
    bad_seat = conn.execute(
        "SELECT COUNT(*) FROM ("
        "  SELECT bi.id FROM board_instance bi "
        "  JOIN seating s ON s.match_id=bi.match_id AND s.room=bi.room "
        "  GROUP BY bi.id HAVING COUNT(DISTINCT s.seat) < 4)"
    ).fetchone()[0]
    if bad_seat:
        problems.append(f"{bad_seat} board_instances missing full seating")

    # every auction's instance exists (referential)
    orphan = conn.execute(
        "SELECT COUNT(*) FROM auction a LEFT JOIN board_instance bi "
        "ON bi.id=a.board_instance_id WHERE bi.id IS NULL"
    ).fetchone()[0]
    if orphan:
        problems.append(f"{orphan} auctions with no board_instance")

    return problems
