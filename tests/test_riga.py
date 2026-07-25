"""Goldens for EBL Riga 2026 (SPEC 10).

EBL 403s datacenter/cloud IPs (SPEC 4.6), so these fixtures must be fetched
from a residential connection (run `python ingest/fetch_fixtures.py` on
Gregor's Mac). Until the four riga/ fixtures exist, these tests skip; once
present they must all pass, per M0's definition of done.
"""
from collections import Counter

import pytest

from conftest import FIXTURES
import parse

RIGA = FIXTURES / "riga"

BOARDACROSS = RIGA / "boardacross_001.01..2620.html"
ROUNDTEAMS = RIGA / "roundteams_r1.html"
BOARDDETAILS = RIGA / "boarddetails_158726.html"
HANDSACROSS = RIGA / "handsacross_r1.html"

missing = pytest.mark.skipif  # alias for readability


@missing(not BOARDACROSS.exists(), reason="EBL fixture not fetched (SPEC 4.6 IP block)")
def test_boardacross_header_and_hands():
    ba = parse.parse_boardacross(BOARDACROSS.read_bytes())
    d = ba.deal
    assert (d.board_no, d.dealer, d.vul) == (1, "N", "NONE")
    # SPEC 10 hands (♠.♥.♦.♣)
    assert d.hand_n == "542.8.Q764.K8542"
    assert d.hand_e == "J87.KQT763.KJT.9"
    assert d.hand_s == "AT3.A942.A93.Q73"
    assert d.hand_w == "KQ96.J5.852.AJT6"
    assert d.all_cards_ok()


@missing(not BOARDACROSS.exists(), reason="EBL fixture not fetched (SPEC 4.6 IP block)")
def test_boardacross_tooltip_count_and_dealer_first():
    ba = parse.parse_boardacross(BOARDACROSS.read_bytes())
    assert len(ba.auctions) == 30  # 30 tables per deal
    for a in ba.auctions:
        assert a.first_seat == "N"


@missing(not BOARDACROSS.exists(), reason="EBL fixture not fetched (SPEC 4.6 IP block)")
def test_board1_first_call_tallies():
    ba = parse.parse_boardacross(BOARDACROSS.read_bytes())
    # dealer North => calls[0]=N, [1]=E, [2]=S, [3]=W
    north = Counter(a.calls[0] for a in ba.auctions)
    assert north == Counter({"P": 29, "3C": 1})

    east = Counter(a.calls[1] for a in ba.auctions if a.calls[0] == "P")
    assert sum(east.values()) == 29
    assert east == Counter({"1H": 21, "2H": 6, "2D": 2})

    south = Counter(
        a.calls[2] for a in ba.auctions
        if a.calls[0] == "P" and a.calls[1] == "1H"
    )
    assert sum(south.values()) == 21
    assert south["P"] == 18 and south["X"] == 3


@missing(not ROUNDTEAMS.exists(), reason="EBL fixture not fetched (SPEC 4.6 IP block)")
def test_roundteams():
    rt = parse.parse_roundteams(ROUNDTEAMS.read_bytes())
    assert len(rt.matches) == 15  # 15 matches in round 1
    ids = {m.ext_match_id for m in rt.matches}
    assert {158726, 158739, 158729} <= ids
    assert rt.handsacross_href and rt.boardacrossfullround_href


@missing(not BOARDDETAILS.exists(), reason="EBL fixture not fetched (SPEC 4.6 IP block)")
def test_boarddetails_seating():
    bd = parse.parse_boarddetails(BOARDDETAILS.read_bytes())
    # SPEC 4.5 / 10: Switzerland v Croatia, qmatchid 158726
    assert bd.seating.open == {
        "N": "MULTON Franck", "W": "DJILOVIC Josko",
        "E": "MIJIC Ante", "S": "ZIMMERMANN Pierre",
    }
    assert bd.seating.closed == {
        "N": "VIDOVIC Toni", "W": "KLUKOWSKI Michal",
        "E": "KALITA Jacek", "S": "KATUSIC Filip",
    }
    assert bd.n_tooltips == 32  # 16 boards x 2 rooms


@missing(not HANDSACROSS.exists(), reason="EBL fixture not fetched (SPEC 4.6 IP block)")
def test_handsacross():
    deals = parse.parse_handsacross(HANDSACROSS.read_bytes())
    assert len(deals) >= 16
    b1 = next(d for d in deals if d.board_no == 1)
    assert b1.hand_n == "542.8.Q764.K8542"
    for d in deals:
        assert d.all_cards_ok()
