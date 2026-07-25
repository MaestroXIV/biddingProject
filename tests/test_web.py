"""Smoke tests for the browse UI (SPEC 7). Skips when the DB isn't built
(data/boardbase.db is local-only); runs full when it is present."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "web"))
DB = ROOT / "data" / "boardbase.db"

pytestmark = pytest.mark.skipif(
    not DB.exists(), reason="boardbase.db not built (run `bb reparse`)")


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    import app
    return TestClient(app.app)


def test_home_ok(client):
    assert client.get("/").status_code == 200


def test_uc1_pair_openings(client):
    # SPEC 2/10: Kalita-Klukowski opened 1C on 61 Riga boards
    r = client.get("/?tournament=riga&player=KLUKOWSKI&partner=KALITA"
                   "&pair_side=opening&opening_call=1C")
    assert r.status_code == 200
    assert "61 board instances match" in r.text


def test_uc3_traveller_and_filter(client):
    r = client.get("/deal/1")
    assert r.status_code == 200
    assert "30 tables" in r.text                      # full field
    assert "BoardAcross.asp?qboard=001.01..2620" in r.text   # provenance (UC7)
    assert '<table class="auc"' in r.text             # auctions rendered
    # SPEC 10: board 1, East opened 2H at 6 tables
    assert "6 tables" in client.get("/deal/1?opening_call=2H").text


def test_uc5_player_view(client):
    r = client.get("/?tournament=riga&player=KLUKOWSKI+Michal&player_role=opener")
    assert r.status_code == 200
    assert "board instances match" in r.text


def test_uc2_sequence_explorer(client):
    # SPEC 7.3: after their 1C opening, K-K's responses (uncontested tree)
    r = client.get("/explore?tournament=riga&player=KLUKOWSKI&partner=KALITA"
                   "&pair_side=opening&seq=1C")
    assert r.status_code == 200
    assert "<b>24</b> auctions match" in r.text          # uncontested 1C openings
    assert "next call" in r.text                   # faceting table rendered
    # drill one level: opener's rebid after 1C 1H exists
    r2 = client.get("/explore?tournament=riga&seq=1C+1H")
    assert r2.status_code == 200
    assert "<b>330</b> auctions match" in r2.text


def test_uc6_situational_hcp(client):
    # SPEC 2 uc6: auctions starting 1NT (2H), next hand 8-11 HCP -> what did they do
    r = client.get("/explore?tournament=riga&seq=1NT+(2H)"
                   "&next_hcp_min=8&next_hcp_max=11")
    assert r.status_code == 200
    assert "<b>51</b> auctions match" in r.text
    assert "Dbl" in r.text                          # a common action shows up


def test_csv_export(client):
    r = client.get("/export.csv?tournament=riga&player=KLUKOWSKI&partner=KALITA"
                   "&pair_side=opening&opening_call=1C")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    rows = [ln for ln in r.text.strip().splitlines() if ln]
    assert len(rows) == 62  # header + 61
    assert "source_url" in rows[0]
