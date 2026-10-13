"""Goldens for the 2026 "cards" layout, pairs and knockout parsers (PAIRS_KO.md §5)."""
import pytest

from conftest import FIXTURES
import parse

K = FIXTURES / "katowice"


def _read(name: str) -> bytes:
    return (K / name).read_bytes()


# --- layout + qboard ----------------------------------------------------------

def test_page_layout_detects_cards_and_classic():
    for f in K.iterdir():
        if f.name == "results_links.html":   # landing-page link list, not a results page
            continue
        assert parse.page_layout(f.read_bytes()) == "cards", f.name
    for sub in ("herning", "riga"):
        for f in (FIXTURES / sub).iterdir():
            assert parse.page_layout(f.read_bytes()) == "classic", f.name


@pytest.mark.parametrize("href,expected", [
    ("BoardAcross.asp?qboard=001.01..2642&qdesktop=0", (1, 1, None, 2642)),
    ("qboard=001.01..2642", (1, 1, None, 2642)),
    ("BoardAcrossKO.asp?qboard=001.02.16.2653", (1, 2, "16", 2653)),
    ("qboard=014.03.QF.2650", (14, 3, "QF", 2650)),
    ("qboard=7", (7, None, None, None)),
    ("BoardAcrossPairs.asp?qtournid=2646&qroundno=1&qgroupno=2&qdesktop=0&qboard=12",
     (12, None, None, None)),
])
def test_parse_qboard(href, expected):
    assert parse.parse_qboard(href) == expected


# --- pairs traveller ------------------------------------------------------------

def test_pairs_b1_deal_and_board_list():
    pb = parse.parse_boardacross_pairs(_read("boardacrosspairs_2646_g2_r1_b1.html"))
    d = pb.deal
    assert (d.board_no, d.dealer, d.vul) == (1, "N", "NONE")
    assert d.hand_n == "Q4.Q652.QJ4.AQJ4"
    assert d.hand_s == "KJ975.-.AK765.KT2"
    assert d.all_cards_ok()
    assert len(pb.board_hrefs) == 16
    assert pb.board_hrefs[0].endswith("qboard=1")
    assert pb.board_hrefs[-1].endswith("qboard=16")
    assert len(pb.tables) == 13


def test_pairs_b1_table1():
    t = parse.parse_boardacross_pairs(_read("boardacrosspairs_2646_g2_r1_b1.html")).tables[0]
    assert (t.section, t.table_no) == ("Sec 1", 1)
    assert t.ns_pair_id == 3014
    assert t.ns_players == ["ANKIERSZTEJN Andrzej", "BARYLA Zdzislaw"]
    assert (t.mp_ns, t.pct_ns) == (22.0, 91.67)
    assert t.ew_pair_id == 3001
    assert t.ew_players == ["KULPINSKI Dariusz", "KRUCZEK Boguslaw"]
    assert (t.mp_ew, t.pct_ew) == (2.0, 8.33)
    assert (t.contract, t.declarer, t.lead, t.tricks) == ("6D", "S", "HA", 12)
    assert (t.score_ns, t.score_ew) == (920, None)
    a = t.auction
    assert a.first_seat == "N"
    assert " ".join(a.calls) == "1C 2D X P 2NT P 3S P 3NT P 4D P 5D P 6D P P P"
    assert a.contract == "6D"
    assert parse.auction_complete(a.calls)


def test_pairs_b1_all_tables():
    tables = parse.parse_boardacross_pairs(_read("boardacrosspairs_2646_g2_r1_b1.html")).tables
    assert [f"{t.contract} {t.declarer}" for t in tables] == [
        "6D S", "3Hx E", "3NT N", "4S S", "6D S", "4S S", "5D S", "4H E",
        "3NT N", "4S S", "3NT N", "6D N", "4S S"]
    signed = [t.score_ns if t.score_ns is not None else -t.score_ew for t in tables]
    assert signed == [920, 300, 430, 480, 920, 450, 420, 150, -150, 480, 520, 920, 480]
    assert (tables[8].score_ns, tables[8].score_ew) == (None, 150)
    assert sum(t.auction is None for t in tables) == 0
    for t in tables:
        assert t.auction.first_seat == "N"  # dealer N
        assert parse.auction_complete(t.auction.calls)


def test_pairs_b2_adj_and_missing_bidpanel():
    pb = parse.parse_boardacross_pairs(_read("boardacrosspairs_2644_g2_r1_b2_excerpt.html"))
    t = pb.tables
    assert len(t) == 4
    assert [(x.contract, x.declarer) for x in t] == [
        ("4H", "N"), ("4H", "N"), ("Adj", ""), ("4H", "N")]
    adj = t[2]
    assert (adj.score_ns, adj.score_ew) == (20, None)
    assert adj.auction is None
    assert adj.lead == "" and adj.tricks is None
    assert t[0].auction is not None and t[1].auction is not None
    assert t[3].auction is None  # no .bidpanel
    assert t[3].tricks == 11


def test_pairs_b12_doubled_pass_and_ew_score():
    t = parse.parse_boardacross_pairs(_read("boardacrosspairs_2644_g2_r1_b12_excerpt.html")).tables
    assert [(x.contract, x.declarer) for x in t] == [
        ("4Hx", "E"), ("3S", "N"), ("Pass", ""), ("3S", "N")]
    assert (t[1].score_ns, t[1].score_ew) == (None, 100)
    passed = t[2]
    assert (passed.score_ns, passed.score_ew) == (0, 0)
    assert passed.auction.calls == ["P", "P", "P", "P"]
    assert passed.auction.contract == "Pass"
    assert t[3].auction is None
    assert "XX" in t[1].auction.calls  # 'xx' cell


def test_pairs_empty_shell_raises():
    shell = ("<!DOCTYPE html><html><head><title>Pairs</title></head><body>"
             "<div class='wrap'><div class='topbar'></div><p class='foot'>"
             "&copy;</p></div></body></html>")
    with pytest.raises(parse.EmptyPage):
        parse.parse_boardacross_pairs(shell)
    assert issubclass(parse.EmptyPage, ValueError)


# --- teams cards: BoardDetails / RoundTeams / handsacross -------------------

def test_cards_boarddetails():
    bd = parse.parse_boarddetails(_read("boarddetails_163531.html"))
    assert bd.seating.open == {"N": "TUSZYNSKI Piotr", "W": "BERENDREGT Carel",
                               "E": "IJSSELMUIDEN Peter", "S": "KOWALSKI Apolinary"}
    assert bd.seating.closed == {"N": "VAN DER NEUT Jaap", "W": "MILNER Reese",
                                 "E": "LALL Hemant", "S": "ZWART Peter"}
    assert (bd.home_team, bd.home_team_id) == ("MILNER", 3001)
    assert (bd.visiting_team, bd.visiting_team_id) == ("VALLON", 3002)
    assert bd.segment == 1
    assert bd.n_tooltips == 0
    assert len(bd.instances) == 28
    assert [i.room for i in bd.instances[:4]] == ["Open", "Closed", "Open", "Closed"]
    assert sorted({i.board_no for i in bd.instances}) == list(range(1, 15))
    assert len(bd.auctions) == sum(i.auction is not None for i in bd.instances)

    o, c = bd.instances[0], bd.instances[1]
    assert (o.board_no, o.contract, o.declarer, o.lead, o.tricks) == (1, "4H", "N", "S7", 11)
    assert (o.score_ns, o.score_ew) == (450, None)
    assert " ".join(o.auction.calls) == "1NT P 4D P 4H P P P"
    assert o.auction.first_seat == "N"
    assert (c.board_no, c.contract, c.declarer, c.lead, c.tricks) == (1, "4H", "N", "S6", 13)
    assert (c.score_ns, c.score_ew) == (510, None)
    assert " ".join(c.auction.calls) == "1NT P 2D P 2H P 4H P P P"


def test_cards_boarddetails_board_link_qboard():
    from selectolax.parser import HTMLParser
    tree = HTMLParser(parse.decode(_read("boarddetails_163531.html")))
    href = tree.css_first("div.board-card .brd").attributes["href"]
    assert "qboard=001.01..2642" in href
    assert parse.parse_qboard(href) == (1, 1, None, 2642)


def test_cards_roundteams():
    rt = parse.parse_roundteams(_read("roundteams_2642_r1.html"))
    m = rt.matches[0]
    assert (m.ext_match_id, m.table_no) == (163531, 61)
    assert (m.home_team, m.home_team_id) == ("MILNER", 3001)
    assert (m.visiting_team, m.visiting_team_id) == ("VALLON", 3002)
    assert rt.handsacross_href == "handsacross.asp?qtournid=2642&qround=1"
    assert len({x.ext_match_id for x in rt.matches}) == len(rt.matches)
    assert 3001 in rt.team_ids and 3002 in rt.team_ids
    assert "Senior Teams" in rt.title


def test_cards_handsacross():
    deals = parse.parse_handsacross(_read("handsacross_2642_r1.html"))
    assert len(deals) == 14
    d1, d2 = deals[0], deals[1]
    assert (d1.board_no, d1.dealer, d1.vul) == (1, "N", "NONE")
    assert d1.hand_n == "AKQ3.A84.QJ5.J95"
    assert (d2.board_no, d2.dealer, d2.vul) == (2, "E", "NS")
    assert all(d.all_cards_ok() for d in deals)


def test_cards_hand_rows_void_and_spaced():
    html = ("<div class='deal-card'><a class='dc-brd'>5</a><span class='dc-info'>"
            "Dealer <b>North</b><br><b>N-S</b> vulnerable</span><div class='deal'>"
            + "".join(
                f"<div class='pos-{p}'><div class='hand'>"
                f"<div class='row'><span class='su'>&spades;</span>{s}</div>"
                f"<div class='row'><span class='su red'>&hearts;</span>{h}</div>"
                f"<div class='row'><span class='su red'>&diams;</span>{d}</div>"
                f"<div class='row'><span class='su'>&clubs;</span>{c}</div></div></div>"
                for p, s, h, d, c in [
                    ("n", "A K Q J T 9 8 7 6 5 4 3 2", "&#8211;", "", "&ndash;"),
                    ("w", "", "AKQJT98765432", "", ""),
                    ("e", "", "", "A K Q J T 9 8 7 6 5 4 3 2", ""),
                    ("s", "", "", "", " AKQJT98765432"),
                ]) + "</div></div>")
    (d,) = parse.parse_handsacross(html)
    assert (d.board_no, d.dealer, d.vul) == (5, "N", "NS")
    assert d.hand_n == "AKQJT98765432.-.-.-"
    assert d.hand_w == "-.AKQJT98765432.-.-"
    assert d.hand_e == "-.-.AKQJT98765432.-"
    assert d.hand_s == "-.-.-.AKQJT98765432"
    assert d.all_cards_ok()


def test_cards_boarddetails_empty_shell_raises():
    shell = ("<html><body><div class='wrap'><div class='topbar'><div class='evhead'>"
             "<div class='cell title'>2026 World Bridge Series</div></div></div>"
             "</div></body></html>")
    with pytest.raises(parse.EmptyPage):
        parse.parse_boarddetails(shell)


# --- pairs / KO navigation -----------------------------------------------------

TOTALPAIRS = """<html><body>
<select class="navsel">
 <option value="?qtournid=2644&qgroupno=1&qroundno=6&qresulttype=cumulative" selected>Final</option>
 <option value="?qtournid=2644&qgroupno=3&qroundno=4&qresulttype=cumulative">SemiFinal A</option>
 <option value="?qtournid=2644&qgroupno=4&qroundno=4&qresulttype=cumulative">SemiFinal B</option>
 <option value="?qtournid=2644&qgroupno=2&qroundno=3&qresulttype=cumulative">Qualifier</option>
</select>
<select class="navsel">
 <option value="TotalPairs.asp?qtournid=2644&qgroupno=1&qroundno=6&qresulttype=cumulative" selected>Open Pairs</option>
 <option value="TotalPairs.asp?qtournid=2645&qgroupno=1&qroundno=6&qresulttype=cumulative">Women Pairs</option>
 <option value="TotalPairs.asp?qtournid=2646&qgroupno=1&qroundno=3&qresulttype=cumulative">Senior Pairs</option>
</select>
<a href="BoardAcrossPairs.asp?qboard=1&qtournid=2644&qroundno=6&qgroupno=1">1</a>
</body></html>"""


def test_parse_pairs_phases_play_order():
    phases = parse.parse_pairs_phases(TOTALPAIRS, 2644)
    assert [(p.code, p.name, p.last_session) for p in phases] == [
        ("2", "Qualifier", 3), ("4", "SemiFinal B", 4),
        ("3", "SemiFinal A", 4), ("1", "Final", 6)]


def test_parse_pairs_phases_ignores_event_and_board_selects():
    # the event dropdown has a 2646 option with qgroupno; must not count as a phase
    assert parse.parse_pairs_phases(TOTALPAIRS, 2646) == []
    # the traveller's board picker (qboard options) is not a phase list either
    assert parse.parse_pairs_phases(_read("boardacrosspairs_2646_g2_r1_b1.html"), 2646) == []


def test_parse_pairs_event_names():
    assert parse.parse_pairs_event_names(TOTALPAIRS) == {
        2644: "Open Pairs", 2645: "Women Pairs", 2646: "Senior Pairs"}
    names = parse.parse_pairs_event_names(_read("boardacrosspairs_2646_g2_r1_b1.html"))
    assert names[2646] == "Senior Pairs"
    assert names[2677] == "President's Cup"
    assert len(names) == 7


KOPHASE = """<html><body>
<select class="navsel">
 <option value="?qtournid=2650&qphase=16&qdesktop=0">Open Teams - Phase of 16</option>
 <option value="?qtournid=2653&qphase=32&qdesktop=0">Mixed Teams - Phase of 32</option>
 <option value="?qtournid=2653&qphase=16&qdesktop=0" selected>Mixed Teams - Phase of 16</option>
 <option value="?qtournid=2653&qphase=QF&qdesktop=0">Mixed Teams - Quarter Final</option>
 <option value="?qtournid=2653&qphase=SF&qdesktop=0">Mixed Teams - Semi Final</option>
 <option value="?qtournid=2653&qphase=FF&qdesktop=0">Mixed Teams - Final</option>
</select>
<table>
 <tr><td><a href="BoardDetailsKO.asp?qmatchid=164176&qphase=16">1</a></td>
     <td><a href="BoardDetailsKO.asp?qmatchid=164177&amp;qphase=16">2</a></td>
     <td><a href="BoardDetailsKO.asp?qmatchid=164176&qphase=16">x</a></td></tr>
 <tr><td><a href="BoardDetailsKO.asp?qmatchid=164190&qphase=16">1</a></td>
     <td><a href="BoardDetailsKO.asp?qmatchid=164177&qphase=16">2</a></td>
     <td><a href="boarddetailsko.asp?qmatchid=164191&qphase=16">3</a></td>
     <td><a href="BoardDetailsKO.asp?qmatchid=164190&qphase=16">t</a></td></tr>
 <tr><td><a href="BoardDetails.asp?qmatchid=999">not ko</a></td></tr>
</table></body></html>"""


def test_parse_ko_phases():
    phases = parse.parse_ko_phases(KOPHASE, 2653)
    assert [(p.code, p.name, p.last_session) for p in phases] == [
        ("32", "Mixed Teams - Phase of 32", None),
        ("16", "Mixed Teams - Phase of 16", None),
        ("QF", "Mixed Teams - Quarter Final", None),
        ("SF", "Mixed Teams - Semi Final", None),
        ("FF", "Mixed Teams - Final", None)]
    assert [p.code for p in parse.parse_ko_phases(KOPHASE, 2650)] == ["16"]


def test_parse_ko_match_ids():
    assert parse.parse_ko_match_ids(KOPHASE) == [164176, 164177, 164190, 164191]
    assert parse.parse_ko_match_ids("<html><body></body></html>") == []


# --- extra real pages added at integration ------------------------------------

def test_real_totalpairs_phases_and_event_names():
    raw = (K / "totalpairs_2644_g2_r1_head.html").read_bytes()
    phases = parse.parse_pairs_phases(raw, 2644)
    assert phases[0].name == "Qualifier" and phases[-1].name == "Final"
    assert {p.name for p in phases} == {"Qualifier", "SemiFinal A", "SemiFinal B", "Final"}
    assert all(p.last_session == 6 for p in phases)
    names = parse.parse_pairs_event_names(raw)
    assert names[2644] == "Open Pairs" and names[2677] == "President's Cup" and len(names) == 7


def test_real_boarddetails_ko_segment_and_teams():
    raw = (K / "boarddetailsko_164177.html").read_bytes()
    assert parse.page_layout(raw) == "cards"
    bd = parse.parse_boarddetails(raw)
    assert (bd.home_team, bd.visiting_team, bd.home_team_id, bd.segment) == ("SIVY B", "GR4S", None, 2)
    assert len(bd.instances) == 28 and bd.instances[0].board_no == 15
    assert bd.seating.open["N"] == "ROSENBERG Michael"
    assert [p.code for p in parse.parse_ko_phases(raw, 2653)] == ["32", "16", "QF", "SF", "FF"]


def test_real_landing_page_classification():
    import discover
    html = (K / "results_links.html").read_text()
    base, entries = discover.classify_landing(
        html, "http://db.worldbridge.org/Repository/tourn/Katowice.26/microSite/Results.htm")
    assert base.endswith("/Katowice.26/microSite/Asp/")
    kinds = {e["tournid"]: e["kind"] for e in entries}
    assert len(kinds) == 28
    assert [t for t, k in kinds.items() if k == "pairs"] == [2644, 2645, 2646, 2647, 2671, 2676, 2677]
    assert [t for t, k in kinds.items() if k == "ko"] == [2650, 2651, 2652, 2653]
