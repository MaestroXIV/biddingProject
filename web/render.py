"""Rendering helpers: suit symbols (♥♦ red), hands, and W-N-E-S auction grids
aligned from the dealer with the opening bid highlighted (SPEC 7)."""
from __future__ import annotations

from markupsafe import Markup, escape

SUIT_SYM = {"S": "♠", "H": "♥", "D": "♦", "C": "♣"}
RED = {"H", "D"}
SEATS_WNES = ("W", "N", "E", "S")
_SEQ = ("N", "E", "S", "W")  # rotation order from dealer


def _suit_span(letter: str) -> str:
    cls = "red" if letter in RED else "blk"
    return f'<span class="{cls}">{SUIT_SYM[letter]}</span>'


def call_html(token: str) -> Markup:
    if token in ("", "-"):
        return Markup("&nbsp;")
    if token.startswith("(") and token.endswith(")"):   # defender call in from_opener
        return Markup(f"({call_html(token[1:-1])})")
    if token == "P":
        return Markup('<span class="pass">Pass</span>')
    if token == "X":
        return Markup('<span class="dbl">Dbl</span>')
    if token == "XX":
        return Markup('<span class="dbl">Rdbl</span>')
    level, strain = token[0], token[1:]
    if strain == "NT":
        return Markup(f"{level}NT")
    return Markup(f"{level}{_suit_span(strain)}")


def hand_html(hand: str) -> Markup:
    """'KJ72.T8.76.T8652' -> ♠KJ72 ♥T8 ♦76 ♣T8652 (glyphs coloured)."""
    parts = []
    for letter, cards in zip("SHDC", hand.split(".")):
        shown = "" if cards == "-" else escape(cards)
        parts.append(f'{_suit_span(letter)}&nbsp;{shown}')
    return Markup('<span class="hand">' + " ".join(parts) + "</span>")


def auction_grid(calls: list[str], dealer: str, opener_rel_pos: int | None):
    """Return rows of 4 cells (W,N,E,S) with the opening call flagged.

    Each cell is (html, is_opening). Leading cells before the dealer and
    trailing cells after the last call are blank.
    """
    lead_blanks = SEATS_WNES.index(dealer)
    cells: list[tuple[Markup, bool]] = [(Markup("&nbsp;"), False)] * lead_blanks
    for i, tok in enumerate(calls):
        cells.append((call_html(tok), (opener_rel_pos is not None and i == opener_rel_pos - 1)))
    while len(cells) % 4 != 0:
        cells.append((Markup("&nbsp;"), False))
    return [cells[i:i + 4] for i in range(0, len(cells), 4)]


def auction_oneliner(from_opener: str | None, calls: list[str], dealer: str):
    """Compact one-line auction for result cards."""
    src = from_opener.split() if from_opener else calls
    out = []
    for tok in src:
        paren = tok.startswith("(") and tok.endswith(")")
        inner = tok[1:-1] if paren else tok
        h = call_html(inner)
        out.append(Markup(f"({h})") if paren else h)
    return Markup(" ".join(str(x) for x in out))


def _num(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".")


def pct(v) -> str:
    """Board percentage for pairs (91.67 -> '91.67%'); '' when unknown."""
    return "" if v is None else f"{_num(v)}%"


def mp(v) -> str:
    return "" if v is None else _num(v)
