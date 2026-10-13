"""Pipeline for the 'pairs' and 'ko' tournament kinds (PAIRS_KO.md §2/§3):
crawl (fake fetcher) -> store -> derive -> integrity on a temp rawcache + temp
DB assembled from the Katowice fixtures. Never touches data/."""
import importlib
import json
import shutil
import sqlite3

import pytest

from conftest import FIXTURES

K = FIXTURES / "katowice"
BASE = "http://db.worldbridge.org/Repository/tourn/Katowice.26/microSite/Asp/"
EMPTY = b"<html><head><title>x</title></head><body><div class='wrap'></div></body></html>"


def tp_page(tournid: int, phases: list[tuple[int, str, int]], extra: str = "") -> bytes:
    """Synthetic TotalPairs page: phase select (most significant first, like the
    site) + the events select. phases = [(qgroupno, name, last_session)]."""
    ph = "".join(f'<option value="?qtournid={tournid}&qgroupno={g}&qroundno={s}">{n}</option>'
                 for g, n, s in phases)
    ev = ('<option value="TotalPairs.asp?qtournid=2644&qgroupno=1&qroundno=6">Open Pairs</option>'
          '<option value="TotalPairs.asp?qtournid=2646&qgroupno=1&qroundno=3">Senior Pairs</option>')
    return (f'<html><body><select class="navsel">{ph}</select>'
            f'<select class="navsel">{ev}</select>{extra}</body></html>').encode()


def ko_page(tournid: int, match_ids: list[int], phase: str) -> bytes:
    opts = (f'<option value="Knockoutphase.asp?qtournid={tournid}&qphase=16">Open Teams - Phase of 16</option>'
            f'<option value="Knockoutphase.asp?qtournid={tournid}&qphase=QF">Open Teams - Quarterfinal</option>'
            '<option value="Knockoutphase.asp?qtournid=2651&qphase=16">Women Teams - Phase of 16</option>')
    links = "".join(f'<a href="BoardDetailsKO.asp?qmatchid={m}&qphase={phase}">x</a>'
                    for m in match_ids)
    return f"<html><body><select>{opts}</select>{links}</body></html>".encode()


@pytest.fixture
def env(tmp_path, monkeypatch):
    import crawl, discover, registry, store
    for mod in (crawl, discover):
        monkeypatch.setattr(mod, "CACHE_ROOT", tmp_path / "rawcache")
    monkeypatch.setattr(registry, "USER_REGISTRY", tmp_path / "tournaments.json")
    monkeypatch.setattr(registry, "TOURNAMENTS", dict(registry.TOURNAMENTS))
    conn = store.connect(tmp_path / "test.db")
    yield tmp_path, conn
    conn.close()


def T(key, tournid, kind, name="X"):
    from registry import Tournament
    return Tournament(key=key, site="WBF", base=BASE, tournid=tournid, name=name,
                      year=2026, series=name, kind=kind)


def put(t, name, data):
    import crawl
    p = crawl.cache_path(t, name)
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        p.write_bytes(data)
    else:
        shutil.copy(data, p)


class FakeFetcher:
    """Serves pages from a dict; unknown URL -> HTTP-like error. Cache-first."""

    def __init__(self, pages: dict[str, bytes]):
        self.pages, self.calls = pages, []

    def get(self, url, cache_path):
        if cache_path.exists():
            return cache_path.read_bytes()
        self.calls.append(url)
        if url not in self.pages:
            raise RuntimeError(f"404 {url}")
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(self.pages[url])
        return self.pages[url]


def q(conn, sql, *args):
    return conn.execute(sql, args).fetchall()


# --- store -> derive -> integrity on a synthetic cache ---------------------------

def build_all(conn):
    """Senior Pairs (2646) S1 B1 + Open Pairs (2644) S1 B2/B12 excerpts + Senior
    Teams (2642) R1, one match."""
    import derive, integrity, store
    senior = T("kat_senior_pairs", 2646, "pairs", "Senior Pairs 2026")
    put(senior, "tp_entry.html", tp_page(2646, [(1, "Final", 2), (2, "Qualifier", 3)]))
    put(senior, "bap_g2_r1_b1.html", K / "boardacrosspairs_2646_g2_r1_b1.html")
    put(senior, "bap_g2_r2_b1.html", EMPTY)            # missing session -> skipped
    open_ = T("kat_open_pairs", 2644, "pairs", "Open Pairs 2026")
    put(open_, "tp_entry.html", tp_page(2644, [(2, "Qualifier", 6)]))
    put(open_, "bap_g2_r1_b2.html", K / "boardacrosspairs_2644_g2_r1_b2_excerpt.html")
    put(open_, "bap_g2_r1_b12.html", K / "boardacrosspairs_2644_g2_r1_b12_excerpt.html")
    put(open_, "bap_g2_r1_b17.html", EMPTY)            # out-of-range board
    teams = T("kat_senior_teams", 2642, "teams", "Senior Teams 2026")
    put(teams, "roundteams_r1.html", K / "roundteams_2642_r1.html")
    put(teams, "boarddetails_163531.html", K / "boarddetails_163531.html")
    put(teams, "handsacross_r1.html", K / "handsacross_2642_r1.html")
    counts = {t.key: store.store_tournament(conn, t) for t in (senior, open_, teams)}
    derive.derive(conn)
    return counts, integrity.check(conn)


def test_pairs_and_teams_end_to_end(env):
    _, conn = env
    counts, problems = build_all(conn)
    assert problems == []
    assert counts["kat_senior_pairs"] == {"rounds": 1, "matches": 13, "deals": 1,
                                          "instances": 13, "auctions": 13}
    assert counts["kat_open_pairs"]["instances"] == 8
    assert counts["kat_open_pairs"]["auctions"] == 5     # Adj + 2 without bidpanel
    assert counts["kat_senior_teams"]["instances"] == 28
    assert counts["kat_senior_teams"]["auctions"] == 28

    kinds = dict(q(conn, "SELECT tourn_code, kind FROM tournament"))
    assert kinds == {2646: "pairs", 2644: "pairs", 2642: "teams"}

    # round: number/label/stage
    rows = q(conn, "SELECT r.number, r.label, r.stage FROM round r JOIN tournament t "
                   "ON t.id=r.tournament_id WHERE t.tourn_code=2646")
    assert rows == [(101, "Qualifier · Session 1", "Qualifier")]
    assert q(conn, "SELECT number, label, stage FROM round r JOIN tournament t "
                   "ON t.id=r.tournament_id WHERE t.tourn_code=2642") == [(1, None, None)]

    # pairs are team rows, the meeting is a match with seats_known=0
    names = dict(q(conn, "SELECT tm.ext_id, tm.name FROM team tm JOIN tournament t "
                         "ON t.id=tm.tournament_id WHERE t.tourn_code=2646"))
    assert names[3014] == "ANKIERSZTEJN – BARYLA"
    assert names[3001] == "KULPINSKI – KRUCZEK"
    (mid, sk, home, vis), = q(conn,
        "SELECT m.id, m.seats_known, h.ext_id, v.ext_id FROM match m "
        "JOIN team h ON h.id=m.home_team_id JOIN team v ON v.id=m.visiting_team_id "
        "WHERE m.ext_match_id=?", 3014 * 100000 + 3001)
    assert (sk, home, vis) == (0, 3014, 3001)
    seats = dict(q(conn, "SELECT s.seat, p.canonical_name FROM seating s JOIN player p "
                         "ON p.id=s.player_id WHERE s.match_id=? AND s.room='Open'", mid))
    assert seats == {"N": "ANKIERSZTEJN Andrzej", "S": "BARYLA Zdzislaw",
                     "E": "KULPINSKI Dariusz", "W": "KRUCZEK Boguslaw"}

    # board_instance mp/pct/table_label + classic scoring
    bi = q(conn, "SELECT bi.id, contract, declarer, lead, tricks, score_ns, score_ew, "
                 "mp_ns, mp_ew, pct_ns, pct_ew, table_label, room FROM board_instance bi "
                 "WHERE match_id=?", mid)
    assert bi[0][1:] == ("6D", "S", "HA", 12, 920, None, 22.0, 2.0, 91.67, 8.33,
                         "Sec 1 Tbl 1", "Open")
    calls, opener_pid, opener_seat, opening = q(
        conn, "SELECT calls, opener_player_id, opener_seat, opening_call FROM auction "
              "WHERE board_instance_id=?", bi[0][0])[0]
    assert calls == "1C 2D X P 2NT P 3S P 3NT P 4D P 5D P 6D P P P"
    assert (opener_pid, opener_seat, opening) == (None, "N", "1C")
    # no pairs auction carries a player-level opener; teams auctions do
    assert q(conn, "SELECT COUNT(*) FROM auction a JOIN board_instance bi ON "
                   "bi.id=a.board_instance_id JOIN match m ON m.id=bi.match_id "
                   "WHERE m.seats_known=0 AND a.opener_player_id IS NOT NULL") == [(0,)]
    assert q(conn, "SELECT COUNT(*) FROM auction a JOIN board_instance bi ON "
                   "bi.id=a.board_instance_id JOIN match m ON m.id=bi.match_id "
                   "WHERE m.seats_known=1 AND a.opener_player_id IS NULL") == [(0,)]
    # pair_key still set for both sides of every pairs instance
    assert q(conn, "SELECT COUNT(*) FROM instance_side s JOIN board_instance bi "
                   "ON bi.id=s.board_instance_id JOIN match m ON m.id=bi.match_id "
                   "WHERE m.seats_known=0 AND s.pair_key IS NOT NULL") == [(2 * 21,)]

    # contracts/scores of the 13 Senior tables
    got = q(conn, "SELECT contract, declarer, score_ns, score_ew FROM board_instance bi "
                  "JOIN deal d ON d.id=bi.deal_id JOIN round r ON r.id=d.round_id "
                  "JOIN tournament t ON t.id=r.tournament_id WHERE t.tourn_code=2646 "
                  "ORDER BY bi.id")
    assert [f"{c} {d}" for c, d, _, _ in got] == [
        "6D S", "3Hx E", "3NT N", "4S S", "6D S", "4S S", "5D S", "4H E", "3NT N",
        "4S S", "3NT N", "6D N", "4S S"]
    assert [ns if ns is not None else -ew for _, _, ns, ew in got] == [
        920, 300, 430, 480, 920, 450, 420, 150, -150, 480, 520, 920, 480]

    # deal + source_url per kind
    (src, dealer, vul, hn), = q(conn,
        "SELECT source_url, dealer, vul, hand_n FROM deal d JOIN round r ON r.id=d.round_id "
        "JOIN tournament t ON t.id=r.tournament_id WHERE t.tourn_code=2646")
    assert src == f"{BASE}BoardAcrossPairs.asp?qboard=1&qtournid=2646&qroundno=1&qgroupno=2"
    assert (dealer, vul, hn) == ("N", "NONE", "Q4.Q652.QJ4.AQJ4")
    assert q(conn, "SELECT source_url FROM deal d JOIN round r ON r.id=d.round_id "
                   "JOIN tournament t ON t.id=r.tournament_id WHERE t.tourn_code=2642 "
                   "AND board_no=1") == [(f"{BASE}BoardAcross.asp?qboard=001.01..2642",)]

    # Open Pairs edge cases: Adj / Pass / no bidpanel
    edge = dict(((c, tl), (ns, ew, has)) for c, tl, ns, ew, has in q(conn,
        "SELECT contract, table_label, score_ns, score_ew, "
        "(SELECT COUNT(*) FROM auction a WHERE a.board_instance_id=bi.id) "
        "FROM board_instance bi JOIN deal d ON d.id=bi.deal_id JOIN round r "
        "ON r.id=d.round_id JOIN tournament t ON t.id=r.tournament_id "
        "WHERE t.tourn_code=2644"))
    assert edge[("Adj", "Sec 4 Tbl 7")] == (20, None, 0)
    assert edge[("Pass", "Sec 9 Tbl 8")] == (0, 0, 1)
    assert edge[("4H", "Sec 11 Tbl 1")][2] == 0
    assert q(conn, "SELECT calls FROM auction a JOIN board_instance bi ON "
                   "bi.id=a.board_instance_id WHERE bi.contract='Pass'") == [("P P P P",)]

    # teams goldens unaffected
    assert q(conn, "SELECT contract, declarer, lead, tricks, score_ns FROM board_instance bi "
                   "JOIN deal d ON d.id=bi.deal_id JOIN match m ON m.id=bi.match_id "
                   "WHERE m.ext_match_id=163531 AND d.board_no=1 ORDER BY room DESC") == [
        ("4H", "N", "S7", 11, 450), ("4H", "N", "S6", 13, 510)]


def test_store_is_idempotent(env):
    import derive, integrity, store
    _, conn = env
    build_all(conn)
    tables = ["tournament", "round", "team", "match", "seating", "deal",
              "board_instance", "auction", "player", "instance_side"]
    before = {t: q(conn, f"SELECT COUNT(*) FROM {t}")[0][0] for t in tables}
    build_all(conn)
    after = {t: q(conn, f"SELECT COUNT(*) FROM {t}")[0][0] for t in tables}
    assert before == after


def test_integrity_flags_guessed_pairs_opener(env):
    import integrity
    _, conn = env
    build_all(conn)
    conn.execute("UPDATE auction SET opener_player_id=1 WHERE board_instance_id IN "
                 "(SELECT bi.id FROM board_instance bi JOIN match m ON m.id=bi.match_id "
                 "WHERE m.seats_known=0 LIMIT 1)")
    assert any("seats-unknown" in p for p in integrity.check(conn))


# --- knockout ------------------------------------------------------------------

def ko_pages(tournid=2650):
    bd = (K / "boarddetails_163531.html").read_bytes()
    ha = (K / "handsacross_2642_r1.html").read_bytes()
    kp = f"{BASE}Knockoutphase.asp?qtournid={tournid}&qphase="
    return {
        kp + "SF": ko_page(tournid, [], "SF"),        # FF missing (404) -> SF is the entry
        kp + "16": ko_page(tournid, [900, 901], "16"),
        kp + "QF": ko_page(tournid, [902, 903], "QF"),
        f"{BASE}BoardDetailsKO.asp?qmatchid=900&qphase=16": bd,
        f"{BASE}BoardDetailsKO.asp?qmatchid=901&qphase=16": bd,
        f"{BASE}BoardDetailsKO.asp?qmatchid=902&qphase=QF": bd,
        # 903 missing -> logged, skipped
        f"{BASE}HandsAcrossKO.asp?qtournid={tournid}&qround=1&qphase=16": ha,
        f"{BASE}HandsAcrossKO.asp?qtournid={tournid}&qround=1&qphase=QF": ha,
    }


def test_crawl_and_store_ko(env):
    import crawl, derive, integrity, store
    tmp, conn = env
    t = T("kat_open_ko", 2650, "ko", "Open Teams KO 2026")
    f = FakeFetcher(ko_pages())
    counts = crawl.crawl(t, f)
    assert counts["phases"] == 2 and counts["boarddetails"] == 3
    assert counts["handsacross"] == 2 and counts["boarddetails_missing"] == 1
    names = sorted(p.name for p in crawl.cache_dir(t).iterdir())
    assert names == ["bdko_900.html", "bdko_901.html", "bdko_902.html",
                     "hako_16_r1.html", "hako_QF_r1.html", "ko_entry.html",
                     "ko_phase_16.html", "ko_phase_QF.html"]
    # a re-crawl is fully cache-served except the still-missing pages
    f2 = FakeFetcher(ko_pages())
    crawl.crawl(t, f2)
    assert all("qmatchid=903" in u or "qphase=FF" in u for u in f2.calls)

    sc = store.store_tournament(conn, t)
    assert sc == {"rounds": 2, "matches": 3, "deals": 28, "instances": 84,
                  "auctions": 84}
    derive.derive(conn)
    assert integrity.check(conn) == []
    assert q(conn, "SELECT number, label, stage FROM round ORDER BY number") == [
        (101, "Phase of 16 · Seg 1", "Phase of 16"),
        (201, "Quarterfinal · Seg 1", "Quarterfinal")]
    assert q(conn, "SELECT kind FROM tournament") == [("ko",)]
    teams = q(conn, "SELECT ext_id, name FROM team ORDER BY name")
    assert [n for _, n in teams] == ["MILNER", "VALLON"]
    assert all(e < 0 for e, _ in teams)
    assert teams[0][0] == store.ko_team_ext_id("MILNER")
    assert q(conn, "SELECT DISTINCT seats_known FROM match") == [(1,)]
    assert q(conn, "SELECT source_url FROM deal d JOIN round r ON r.id=d.round_id "
                   "WHERE r.number=101 AND board_no=1") == [
        (f"{BASE}BoardAcrossKO.asp?qboard=001.01.16.2650",)]
    assert q(conn, "SELECT COUNT(*) FROM auction WHERE opener_player_id IS NULL "
                   "AND opening_call IS NOT NULL") == [(0,)]


def test_ko_team_ext_id_stable():
    import zlib
    import store
    assert store.ko_team_ext_id("POLAND") == -(zlib.crc32(b"POLAND") & 0x7FFFFFFF)
    assert store.ko_stage("Mixed Teams - Phase of 16") == "Phase of 16"


# --- crawl_pairs ---------------------------------------------------------------

def test_crawl_pairs(env):
    import crawl
    tmp, conn = env
    t = T("kat_senior_pairs", 2646, "pairs")
    bap = (K / "boardacrosspairs_2646_g2_r1_b1.html").read_bytes()
    tp = f"{BASE}TotalPairs.asp?qtournid=2646&qgroupno="
    pages = {
        tp + "1&qroundno=1": EMPTY,            # no phases -> not the entry
        tp + "2&qroundno=1": tp_page(2646, [(2, "Qualifier", 3)]),
        crawl.bap_url(t, "2", 1, 1): bap,
        # session 2: board 1 is empty, TotalPairs session page links board 5
        crawl.bap_url(t, "2", 2, 1): EMPTY,
        tp + "2&qroundno=2": b'<a href="BoardAcrosspairs.asp?qboard=5&qtournid=2646">5</a>',
        crawl.bap_url(t, "2", 2, 5): bap,
        # session 3: nothing at all -> skipped
        crawl.bap_url(t, "2", 3, 1): EMPTY,
    }
    for b in range(2, 17):
        pages[crawl.bap_url(t, "2", 1, b)] = bap
    counts = crawl.crawl(t, FakeFetcher(pages))
    assert counts["phases"] == 1 and counts["sessions"] == 2 and counts["empty"] == 1
    assert counts["boards"] == 16 + 1               # S1: all 16; S2: b5 only
    d = crawl.cache_dir(t)
    assert (d / "tp_entry.html").read_bytes() == pages[tp + "2&qroundno=1"]
    assert all((d / f"bap_g2_r1_b{b}.html").exists() for b in range(1, 17))
    assert (d / "bap_g2_r2_b5.html").exists() and (d / "tp_g2_r2.html").exists()
    assert (d / "bap_g2_r2_b1.html").read_bytes() == EMPTY
    # S2's other boards were requested at S2 urls (404 here -> logged, skipped)
    assert counts["board_missing"] == 14


def test_crawl_pairs_no_entry_raises(env):
    import crawl
    t = T("x", 2699, "pairs")
    with pytest.raises(RuntimeError):
        crawl.crawl(t, FakeFetcher({}))


# --- discover / register / glob -------------------------------------------------

LANDING_URL = "http://db.worldbridge.org/Repository/tourn/Katowice.26/Results.htm"
LANDING = f"""<html><body>
<a href="microSite/Asp/TotalPairs.asp?qtournid=2646&qgroupno=1&qroundno=3">Senior Pairs</a>
<a href="microSite/Asp/Knockoutphase.asp?qtournid=2650&qphase=16">Open KO</a>
<a href="microSite/RunningScores/Asp/KnockoutphaseConditStat.asp?qtournid=2650&qphase=16">x</a>
<a href="microSite/RunningScores/Asp/RoundTeamsCondit.asp?qtournid=2650">dup</a>
<a href="microSite/Asp/RoundTeams.asp?qtournid=2642&qroundno=1">Senior Teams</a>
<a href="microSite/RunningScores/Asp/TotalPairsCondit.asp?qtournid=2642">dup</a>
<a href="microSite/RunningScores/Asp/KnockoutphaseConditStat.asp?qtournid=2653&qphase=QF">Mixed KO</a>
<a href="microSite/Asp/Bulletin.asp?qtournid=9999">bulletin</a>
<a href="microSite/Asp/RoundTeams.asp?qtournid=2674&qroundno=1">BAM Final A</a>
<a href="http://example.org/">elsewhere</a>
</body></html>"""


def test_classify_landing():
    import discover
    base, entries = discover.classify_landing(LANDING, LANDING_URL)
    assert base == "http://db.worldbridge.org/Repository/tourn/Katowice.26/microSite/Asp/"
    assert [(e["tournid"], e["kind"]) for e in entries] == [
        (2642, "teams"), (2646, "pairs"), (2650, "ko"), (2653, "ko"), (2674, "teams")]
    assert "RunningScores" not in next(e for e in entries if e["tournid"] == 2650)["href"]
    assert discover.kind_of_href("x/Asp/KnockoutphaseConditStat.asp?qtournid=1") == "ko"
    assert discover.kind_of_href("x/Asp/BoardDetails.asp?qmatchid=1") is None


def test_discover_landing_register_and_glob(env):
    import discover, registry
    tmp, _ = env
    ms = "http://db.worldbridge.org/Repository/tourn/Katowice.26/microSite/Asp/"
    rt = (K / "roundteams_2642_r1.html").read_bytes()
    pages = {
        LANDING_URL: LANDING.encode(),
        f"{ms}TotalPairs.asp?qtournid=2646&qgroupno=1&qroundno=3":
            tp_page(2646, [(2, "Qualifier", 3)]),
        f"{ms}Knockoutphase.asp?qtournid=2650&qphase=16": ko_page(2650, [], "16"),
        f"{ms}KnockoutphaseConditStat.asp?qtournid=2653&qphase=QF":
            ko_page(2653, [], "QF").replace(b"2650", b"2653").replace(b"Open", b"Mixed"),
        f"{ms}RoundTeams.asp?qtournid=2642&qroundno=1": rt,
        f"{ms}RoundTeams.asp?qtournid=2674&qroundno=1": rt,   # same page: name clash
    }
    site, base, entries = discover.discover_landing(LANDING_URL, FakeFetcher(pages))
    assert (site, base) == ("WBF", ms)
    by = {e["tournid"]: e["name"] for e in entries}
    assert by == {2642: "Senior Teams", 2646: "Senior Pairs", 2650: "Open Teams",
                  2653: "Mixed Teams", 2674: "Senior Teams"}
    plan = discover.plan_registrations(entries, site, base, 2026, "katowice26")
    keys = {t.tournid: (t.key, t.kind, t.name) for t in plan}
    assert keys[2646] == ("katowice26_senior_pairs", "pairs", "Senior Pairs 2026")
    assert keys[2650] == ("katowice26_open_teams_ko", "ko", "Open Teams KO 2026")
    assert keys[2642][0] == "katowice26_senior_teams"
    assert keys[2674][0] == "katowice26_senior_teams_2674"
    for t in plan:
        registry.register(t)
    got = registry.select_keys(["katowice26_*"])
    assert sorted(got) == sorted(k for k, _, _ in keys.values())
    assert registry.select_keys(["katowice26_*ko", "riga"]) == [
        "katowice26_open_teams_ko", "katowice26_mixed_teams_ko", "riga"]
    with pytest.raises(KeyError):
        registry.select_keys(["nosuch_*"])
    # JSON round-trips kind
    reloaded = registry._load_user()
    assert reloaded["katowice26_open_teams_ko"].kind == "ko"
    assert reloaded["katowice26_senior_pairs"].kind == "pairs"


def test_registry_old_json_without_kind(tmp_path, monkeypatch):
    import registry
    importlib.reload(registry)
    p = tmp_path / "tournaments.json"
    p.write_text(json.dumps([{"key": "venice25", "site": "WBF", "base": "http://x/Asp/",
                              "tournid": 2551, "name": "Venice Cup 2025",
                              "year": 2025, "series": "Venice Cup"}]))
    monkeypatch.setattr(registry, "USER_REGISTRY", p)
    assert registry._load_user()["venice25"].kind == "teams"
    with pytest.raises(ValueError):
        registry.register(registry.Tournament(key="z", site="WBF", base="b", tournid=1,
                                              name="n", year=1, kind="swiss"))


def test_cli_register_flags_kind(env, monkeypatch):
    import cli, registry
    key = cli._register_from_flags(["--site", "WBF", "--base", BASE, "--tournid", "2650",
                                    "--name", "Open KO", "--year", "2026",
                                    "--kind", "ko", "--key", "kat_ko"])
    assert key == "kat_ko" and registry.TOURNAMENTS["kat_ko"].kind == "ko"
    key = cli._register_from_flags(["--site", "WBF", "--base", BASE, "--tournid", "2642",
                                    "--name", "Senior", "--year", "2026"])
    assert registry.TOURNAMENTS[key].kind == "teams"
