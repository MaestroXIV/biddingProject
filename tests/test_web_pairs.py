"""Web UI on pairs + KO data (PAIRS_KO.md §2): a tiny hand-made DB built with
the real schema/migrations, served through BOARDBASE_DB."""
import shutil
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "web"))
REAL_DB = ROOT / "data" / "boardbase.db"


def build_db(path: Path) -> None:
    import store
    conn = store.connect(path)
    x = conn.execute
    x("INSERT INTO site(id, code) VALUES(1, 'WBF')")
    base = "http://db.worldbridge.org/Repository/tourn/Katowice.26/microSite/Asp/"
    x("INSERT INTO tournament(id, site_id, slug, tourn_code, name, year, asp_base_url, kind)"
      " VALUES(1, 1, 'kat_pairs', 2646, 'Senior Pairs 2026', 2026, ?, 'pairs')", (base,))
    x("INSERT INTO tournament(id, site_id, slug, tourn_code, name, year, asp_base_url, kind)"
      " VALUES(2, 1, 'kat_ko', 2652, 'Senior Teams KO 2026', 2026, ?, 'ko')", (base,))

    names = ["ANKIERSZTEJN Andrzej", "BARYLA Zdzislaw", "KULPINSKI Dariusz",
             "KRUCZEK Boguslaw", "SMITH John", "JONES Bob", "BROWN Tim", "GREEN Al"]
    for i, n in enumerate(names, 1):
        x("INSERT INTO player(id, canonical_name) VALUES(?, ?)", (i, n))
        x("INSERT INTO player_alias(alias, player_id) VALUES(?, ?)", (n, i))

    # ---- pairs: 2 pairs (team rows), 2 meetings (swap of directions) ----
    x("INSERT INTO team(id, tournament_id, ext_id, name) VALUES(1, 1, 3014, 'ANKIERSZTEJN – BARYLA')")
    x("INSERT INTO team(id, tournament_id, ext_id, name) VALUES(2, 1, 3001, 'KULPINSKI – KRUCZEK')")
    x("INSERT INTO round(id, tournament_id, number, label, stage)"
      " VALUES(1, 1, 101, 'Qualifier · Session 1', 'Qualifier')")
    x("INSERT INTO match(id, round_id, ext_match_id, home_team_id, visiting_team_id, seats_known)"
      " VALUES(1, 1, 301403001, 1, 2, 0)")
    x("INSERT INTO match(id, round_id, ext_match_id, home_team_id, visiting_team_id, seats_known)"
      " VALUES(2, 1, 300103014, 2, 1, 0)")
    for mid, (n, s, e, w) in ((1, (1, 2, 3, 4)), (2, (3, 4, 1, 2))):
        for seat, pid in zip("NSEW", (n, s, e, w)):
            x("INSERT INTO seating VALUES(?, 'Open', ?, ?)", (mid, seat, pid))
    x("INSERT INTO deal(id, round_id, board_no, dealer, vul, hand_n, hand_e, hand_s, hand_w, source_url)"
      " VALUES(1, 1, 1, 'N', 'NONE', 'Q4.Q652.QJ4.AQJ4', 'A86.AKJ93.T8.983',"
      " 'KJ975.-.AK765.KT2', 'T32.T874.932.765', ?)",
      (base + "BoardAcrossPairs.asp?qboard=1&qtournid=2646&qroundno=1&qgroupno=2",))
    x("INSERT INTO board_instance(id, deal_id, match_id, room, contract, declarer, lead, tricks,"
      " score_ns, score_ew, mp_ns, mp_ew, pct_ns, pct_ew, table_label)"
      " VALUES(1, 1, 1, 'Open', '6D', 'S', 'HA', 12, 920, NULL, 22, 2, 91.67, 8.33, 'Sec 1 Tbl 1')")
    x("INSERT INTO board_instance(id, deal_id, match_id, room, contract, declarer, lead, tricks,"
      " score_ns, score_ew, mp_ns, mp_ew, pct_ns, pct_ew, table_label)"
      " VALUES(2, 1, 2, 'Open', 'Adj', NULL, '', NULL, 20, NULL, 12, 12, 50, 50, 'Sec 1 Tbl 2')")
    calls = "1C 2D X P 2NT P 3S P 3NT P 4D P 5D P 6D P P P"
    x("INSERT INTO auction(board_instance_id, calls, complete, opener_seat, opener_rel_pos,"
      " opening_call, opener_player_id, opening_side, competitive, vul_rel, from_opener,"
      " uncontested_key) VALUES(1, ?, 1, 'N', 1, '1C', NULL, 'NS', 1, 'none', ?, NULL)",
      (calls, "1C (2D) X (P) 2NT (P) 3S (P) 3NT (P) 4D (P) 5D (P) 6D (P) P (P)"))
    for bi, ns, ew in ((1, "1-2", "3-4"), (2, "3-4", "1-2")):
        for side, key in (("NS", ns), ("EW", ew)):
            lo, hi = key.split("-")
            x("INSERT INTO instance_side VALUES(?, ?, ?, ?, ?)", (bi, side, lo, hi, key))

    # ---- KO: one segment, both rooms, seats known ----
    x("INSERT INTO team(id, tournament_id, ext_id, name) VALUES(3, 2, -11, 'POLAND')")
    x("INSERT INTO team(id, tournament_id, ext_id, name) VALUES(4, 2, -12, 'USA')")
    x("INSERT INTO round(id, tournament_id, number, label, stage)"
      " VALUES(2, 2, 102, 'Phase of 16 · Seg 2', 'Phase of 16')")
    x("INSERT INTO match(id, round_id, ext_match_id, home_team_id, visiting_team_id, seats_known)"
      " VALUES(3, 2, 170001, 3, 4, 1)")
    for room, (n, s, e, w) in (("Open", (1, 2, 5, 6)), ("Closed", (7, 8, 3, 4))):
        for seat, pid in zip("NSEW", (n, s, e, w)):
            x("INSERT INTO seating VALUES(3, ?, ?, ?)", (room, seat, pid))
    x("INSERT INTO deal(id, round_id, board_no, dealer, vul, hand_n, hand_e, hand_s, hand_w, source_url)"
      " VALUES(2, 2, 17, 'E', 'NS', 'Q4.Q652.QJ4.AQJ4', 'A86.AKJ93.T8.983',"
      " 'KJ975.-.AK765.KT2', 'T32.T874.932.765', ?)",
      (base + "BoardAcrossKO.asp?qboard=017.02.1.2652",))
    for bi, room, opener in ((3, "Open", 5), (4, "Closed", 3)):
        x("INSERT INTO board_instance(id, deal_id, match_id, room, contract, declarer, tricks,"
          " score_ns, score_ew) VALUES(?, 2, 3, ?, '4H', 'E', 10, NULL, 420)", (bi, room))
        x("INSERT INTO auction(board_instance_id, calls, complete, opener_seat, opener_rel_pos,"
          " opening_call, opener_player_id, opening_side, competitive, vul_rel, from_opener,"
          " uncontested_key) VALUES(?, '1H P 4H P P P', 1, 'E', 1, '1H', ?, 'EW', 0, 'fav',"
          " '1H (P) 4H (P) P (P)', '1H 4H P')", (bi, opener))
    conn.commit()
    conn.close()


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    p = tmp_path_factory.mktemp("bbweb") / "pairs.db"
    build_db(p)
    return p


@pytest.fixture()
def client(db, monkeypatch):
    from fastapi.testclient import TestClient
    import app
    monkeypatch.setenv("BOARDBASE_DB", str(db))
    return TestClient(app.app)


def test_home_dropdown_shows_kind(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Senior Pairs 2026 · pairs" in r.text
    assert "Senior Teams KO 2026 · KO" in r.text
    assert 'name="stage"' in r.text and ">Phase of 16<" in r.text


def test_search_pairs_cards(client):
    r = client.get("/?tournament=kat_pairs")
    assert r.status_code == 200
    assert "2 board instances match" in r.text          # Adj instance included
    assert "kat_pairs · Qualifier · Session 1 · Board 1" in r.text
    assert "Sec 1 Tbl 1" in r.text and "Sec 1 Tbl 2" in r.text
    assert "NS 91.67% · EW 8.33%" in r.text
    assert ">Open<" not in r.text                        # no room badge for pairs
    # auction filters drop the no-auction instance
    assert "1 board instance match" in client.get(
        "/?tournament=kat_pairs&opening_call=1C").text


def test_search_ko_label_and_stage(client):
    r = client.get("/?stage=Phase+of+16")
    assert "2 board instances match" in r.text
    assert "kat_ko · Phase of 16 · Seg 2 · Board 17" in r.text
    assert "POLAND vs USA" in r.text


def test_pairs_traveller(client):
    r = client.get("/deal/1")
    assert r.status_code == 200
    t = r.text
    assert "Senior Pairs 2026 · Qualifier · Session 1 · Board 1" in t
    assert "2 tables" in t
    assert t.index("Sec 1 Tbl 1") < t.index("Sec 1 Tbl 2")
    assert "ANKIERSZTEJN – BARYLA" in t and "KULPINSKI – KRUCZEK" in t
    assert "91.67%" in t and "22 mp" in t
    assert "no bidding recorded" in t                    # Adj instance kept
    assert t.count('<table class="auc"') == 1
    assert "BoardAcrossPairs.asp?qboard=1&amp;qtournid=2646" in t
    # seats inside a pair unknown -> no player names under W/N/E/S
    assert "<small>ANKIERSZTEJN Andrzej</small>" not in t
    assert "/pair?p1=ANKIERSZTEJN+Andrzej&amp;p2=BARYLA+Zdzislaw" in t


def test_ko_traveller(client):
    t = client.get("/deal/2").text
    assert "Phase of 16 · Seg 2 · Board 17" in t
    assert "POLAND vs USA" in t and t.count('<table class="auc"') == 2
    assert "<small>SMITH John</small>" in t               # seats known in KO


def test_player_page_pairs_note(client):
    r = client.get("/player?name=ANKIERSZTEJN")
    assert r.status_code == 200
    assert "pairs events count at pair level only" in r.text.lower()
    assert "BARYLA Zdzislaw" in r.text                    # partner from pair_key
    r2 = client.get("/player?name=SMITH")                 # KO only: no note
    assert "pair level only" not in r2.text
    assert '1<span class="red">♥</span>' in r2.text       # KO opener grid


def test_pair_page_counts_pairs_openings(client):
    import re
    r = client.get("/pair?p1=ANKIERSZTEJN&p2=BARYLA")
    assert r.status_code == 200
    assert ">pair</span></th>" in r.text
    rows = re.findall(r'<td class="bcall">(.*?)</td>\s*<td class="bcount">(\d+)</td>'
                      r'\s*<td>(\d+)</td>\s*<td>(\d+)</td>\s*<td>(\d+)</td>', r.text, re.S)
    by_call = {re.sub(r"<[^>]+>", "", c).strip(): rest for c, *rest in rows}
    assert by_call["1♣"] == ["1", "0", "0", "1"]          # total, A, B, pair
    s = client.get("/?player=ANKIERSZTEJN&partner=BARYLA&pair_side=opening")
    assert "1 board instance match" in s.text


def test_explore_and_csv(client):
    r = client.get("/explore?tournament=kat_pairs&seq=1C+(2D)")
    assert r.status_code == 200 and "<b>1</b> auction" in r.text
    assert "kat_pairs Qualifier · Session 1·1" in r.text
    c = client.get("/export.csv?tournament=kat_pairs")
    lines = c.text.strip().splitlines()
    assert len(lines) == 3 and "table_label" in lines[0] and "Sec 1 Tbl 2" in c.text


@pytest.mark.skipif(not REAL_DB.exists(), reason="boardbase.db not built")
def test_migrated_real_db_copy(tmp_path, monkeypatch):
    """Old teams DB after store.migrate (new columns present, all NULL/default)."""
    import store
    from fastapi.testclient import TestClient
    import app
    copy = tmp_path / "bb.db"
    shutil.copy(REAL_DB, copy)
    copy.chmod(0o644)
    conn = sqlite3.connect(copy)
    store.migrate(conn)
    conn.close()
    monkeypatch.setenv("BOARDBASE_DB", str(copy))
    c = TestClient(app.app)
    r = c.get("/deal/1")
    assert r.status_code == 200 and "30 tables" in r.text and "Round 1" in r.text
    assert "· pairs" not in c.get("/").text
    r = c.get("/?tournament=riga&player=KLUKOWSKI&partner=KALITA"
              "&pair_side=opening&opening_call=1C")
    assert "61 board instances match" in r.text and "riga · R1 ·" in r.text
    assert c.get("/player?name=KLUKOWSKI+Michal&tournament=riga").status_code == 200


def test_share_build_offline_pairs(db, tmp_path):
    """share/build.py on the pairs DB; if Playwright + Chromium are available,
    the offline file boots and renders a pairs traveller with no console errors."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("bb_share_build", ROOT / "share" / "build.py")
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    out = tmp_path / "bb.html"
    build.main(["--db", str(db), "--out", str(out)])
    html = out.read_text()
    assert "/*__DB_GZ_B64__*/" not in html and "detectColumns" in html

    pw = pytest.importorskip("playwright.sync_api")
    chrome = Path("/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
    with pw.sync_playwright() as p:
        try:
            b = p.chromium.launch(executable_path=str(chrome) if chrome.exists() else None)
        except Exception as e:                       # no browser installed
            pytest.skip(f"chromium unavailable: {e}")
        pg = b.new_page()
        errs = []
        pg.on("console", lambda m: m.type == "error" and errs.append(m.text))
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(out.as_uri())
        pg.wait_for_function(
            "document.getElementById('splash').style.display==='none'", timeout=20000)
        pg.evaluate("location.hash='#/deal/1'")
        pg.wait_for_selector(".traveller")
        t = pg.inner_text("#app")
        pg.evaluate("location.hash='#/player?name=ANKIERSZTEJN'")
        pg.wait_for_selector(".note")
        b.close()
    assert not errs, errs
    for s in ("Qualifier · Session 1 · Board 1", "2 tables", "Sec 1 Tbl 2",
              "no bidding recorded", "91.67%", "ANKIERSZTEJN – BARYLA"):
        assert s in t, s
