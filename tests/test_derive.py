"""Unit tests for the derive/bridge logic (SPEC 5, 6)."""
import bridge
from derive import _canonical, _vul_rel


def test_hcp_and_shape():
    assert bridge.hcp("AKQ4.T82.7.J9532") == 10
    assert bridge.shape("AKQ4.T82.7.J9532") == "4-3-1-5"
    assert bridge.pattern("AKQ4.T82.7.J9532") == "5431"
    assert bridge.is_balanced("KQ96.J5.852.AJT6") is True   # 4-4-3-2
    assert bridge.is_balanced("AT3.A942.A93.Q73") is True   # 3-4-3-3
    assert bridge.is_balanced("AKQ4.T82.7.J9532") is False  # 5-4-3-1


def test_opener_rotation():
    # dealer North, first bid at index 1 => East opened (2nd seat)
    assert bridge.rotate_from("N", 0) == "N"
    assert bridge.rotate_from("N", 1) == "E"
    assert bridge.rotate_from("W", 0) == "W"


def test_canonical_uncontested():
    # dealer N: P(N) 1C(E) P(S) 1H(W) P(N) 1NT(E) ... opener E, side EW
    calls = ["P", "1C", "P", "1H", "P", "1NT", "P", "P", "P"]
    frm, unc, comp = _canonical(calls, dealer="N", opener_idx=1, opening_side="EW")
    assert comp == 0
    assert unc == "1C 1H 1NT"                       # defender + trailing passes stripped
    assert frm == "1C (P) 1H (P) 1NT (P) P (P)"     # defenders in parentheses


def test_canonical_competitive():
    # dealer N: 1C(N) 1S(E) X(S) ... E and side EW act -> competitive, no unc key
    calls = ["1C", "1S", "X", "P", "P", "P"]
    frm, unc, comp = _canonical(calls, dealer="N", opener_idx=0, opening_side="NS")
    assert comp == 1
    assert unc is None
    assert frm == "1C (1S) X (P) P (P)"


def test_vul_rel():
    assert _vul_rel("NONE", "NS") == "none"
    assert _vul_rel("ALL", "NS") == "both"
    assert _vul_rel("NS", "NS") == "unfav"   # we vul, opp not
    assert _vul_rel("EW", "NS") == "fav"     # we not vul, opp vul
