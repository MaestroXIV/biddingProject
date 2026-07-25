"""Small bridge-domain helpers shared by store/derive."""
from __future__ import annotations

SEATS = ("N", "E", "S", "W")           # clockwise rotation order
SIDE = {"N": "NS", "S": "NS", "E": "EW", "W": "EW"}
_HCP = {"A": 4, "K": 3, "Q": 2, "J": 1}


def rotate_from(dealer: str, steps: int) -> str:
    """Seat `steps` positions clockwise from dealer (dealer = step 0)."""
    return SEATS[(SEATS.index(dealer) + steps) % 4]


def is_bid(call: str) -> bool:
    """A contract bid (level+strain), as opposed to P/X/XX."""
    return bool(call) and call[0] in "1234567"


def hcp(hand: str) -> int:
    return sum(_HCP.get(c, 0) for c in hand.replace(".", ""))


def suit_lengths(hand: str) -> list[int]:
    """Lengths in S,H,D,C order ('-' = void)."""
    return [0 if s == "-" else len(s) for s in hand.split(".")]


def shape(hand: str) -> str:
    return "-".join(str(n) for n in suit_lengths(hand))          # e.g. '5-3-3-2'


def pattern(hand: str) -> str:
    return "".join(str(n) for n in sorted(suit_lengths(hand), reverse=True))  # '5332'


def is_balanced(hand: str) -> bool:
    return pattern(hand) in ("4333", "4432", "5332")


def longest_suit(hand: str) -> str:
    lens = suit_lengths(hand)
    return "SHDC"[lens.index(max(lens))]
