"""Goldens for WBF Herning 2025 Bermuda Bowl (SPEC 10)."""
from pathlib import Path

import pytest

from conftest import FIXTURES
import parse

HERNING = FIXTURES / "herning"


def read(name: str) -> bytes:
    return (HERNING / name).read_bytes()


# --- BoardAcross 001.01..2550 ----------------------------------------------

def test_boardacross_header_and_hands():
    ba = parse.parse_boardacross(read("boardacross_001.01..2550.html"))
    d = ba.deal
    assert (d.board_no, d.dealer, d.vul) == (1, "N", "NONE")
    # SPEC 10: North hand
    assert d.hand_n == "KJ72.T8.76.T8652"
    # 52-card invariant
    assert d.all_cards_ok()


def test_boardacross_tooltip_count():
    ba = parse.parse_boardacross(read("boardacross_001.01..2550.html"))
    # 12 tables / 24 auction tooltips (SPEC 10)
    assert len(ba.auctions) == 24


def test_boardacross_dealer_first_invariant():
    ba = parse.parse_boardacross(read("boardacross_001.01..2550.html"))
    # SPEC 4.4: the first real call of every auction belongs to the dealer
    for a in ba.auctions:
        assert a.first_seat == ba.deal.dealer


# --- RoundTeams r1 ----------------------------------------------------------

def test_roundteams_header():
    rt = parse.parse_roundteams(read("roundteams_r1.html"))
    assert "47th World Teams Championships" in rt.title
    assert "Bermuda Bowl" in rt.title


def test_roundteams_matches_and_teams():
    rt = parse.parse_roundteams(read("roundteams_r1.html"))
    assert len(rt.matches) == 12
    ids = [m.ext_match_id for m in rt.matches]
    # SPEC 10: BoardDetails qmatchid range 153334-153345
    assert min(ids) == 153334 and max(ids) == 153345
    assert 153334 in ids
    # SPEC 10: TeamDetails qteamid 1001-1024
    assert min(rt.team_ids) == 1001 and max(rt.team_ids) == 1024
    assert len(rt.team_ids) == 24


def test_roundteams_bulk_links_present():
    rt = parse.parse_roundteams(read("roundteams_r1.html"))
    assert rt.handsacross_href and "handsacross" in rt.handsacross_href.lower()
    assert rt.boardacrossfullround_href
    assert "boardacrossfullround" in rt.boardacrossfullround_href.lower()


# --- BoardDetails 153334 ----------------------------------------------------

def test_boarddetails_seating():
    bd = parse.parse_boarddetails(read("boarddetails_153334.html"))
    # AUSTRALIA vs TUNISIA, round 1 (verified from the page)
    assert bd.seating.open == {
        "N": "HAFFER Joachim", "W": "MEDDEB Omar",
        "E": "MEDDEB Ahmed", "S": "MARKEY Phil",
    }
    assert bd.seating.closed == {
        "N": "FOURATI Moez", "W": "WILTSHIRE David",
        "E": "ASHTON Sophie", "S": "GHODHBANE Mohamed Anis",
    }


def test_boarddetails_tooltips_even():
    bd = parse.parse_boarddetails(read("boarddetails_153334.html"))
    # two rooms per board -> tooltip count is even and non-trivial
    assert bd.n_tooltips >= 2 and bd.n_tooltips % 2 == 0
    assert len(bd.auctions) == bd.n_tooltips


# --- handsacross r1 (M0 probe: SPEC 8.1) ------------------------------------

def test_handsacross_all_deals():
    deals = parse.parse_handsacross(read("handsacross_r1.html"))
    # one page carries every deal of the round, no auctions
    assert len(deals) >= 14
    b1 = next(d for d in deals if d.board_no == 1)
    assert (b1.dealer, b1.vul) == ("N", "NONE")
    assert b1.hand_n == "KJ72.T8.76.T8652"
    for d in deals:
        assert d.all_cards_ok()


def test_handsacross_matches_boardacross():
    """The board-1 diagram must agree between handsacross and BoardAcross."""
    ba = parse.parse_boardacross(read("boardacross_001.01..2550.html")).deal
    ha = next(
        d for d in parse.parse_handsacross(read("handsacross_r1.html"))
        if d.board_no == 1
    )
    assert (ha.hand_n, ha.hand_w, ha.hand_e, ha.hand_s) == (
        ba.hand_n, ba.hand_w, ba.hand_e, ba.hand_s
    )
