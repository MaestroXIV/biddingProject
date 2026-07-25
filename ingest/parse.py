"""Pure parsers for the EBL/WBF microsite pages (SPEC 4).

No network here: every function takes raw page bytes (or a decoded str) and
returns dataclasses. One parser family serves both federations; only the base
URL differs. Pages declare iso-8859-1 (SPEC 4.3) -- decode accordingly.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from selectolax.parser import HTMLParser, Node

# --- primitives -------------------------------------------------------------

SUIT_GLYPH = {"♠": "S", "♥": "H", "♦": "D", "♣": "C"}
SEAT_ORDER = ("W", "N", "E", "S")  # auction/tooltip column order is always W N E S
CARD_CHARS = "AKQJT98765432"


def decode(raw: bytes | str) -> str:
    """Decode a page to str.

    The sites declare iso-8859-1, but a page saved through a browser is often
    re-encoded as UTF-8. Suit symbols are HTML entities (&spades; etc.) either
    way, so only accented player names depend on this. Try UTF-8 first (also
    covers pure ASCII+entities) and fall back to iso-8859-1.
    """
    if isinstance(raw, str):
        return raw
    if raw.startswith(b"\xef\xbb\xbf"):  # UTF-8 BOM
        return raw[3:].decode("utf-8", errors="replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("iso-8859-1")


def _ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def normalize_call(text: str) -> str | None:
    """Normalize one auction cell to a token, or None for a placeholder.

    Placeholders ('-' or blank) mark seats before the dealer or after the final
    pass and are skipped (SPEC 4.4). Returns P, X, XX, or a bid like 1C/2NT.
    """
    t = text.replace("\xa0", " ").strip()
    if t == "" or t == "-":
        return None
    low = t.lower()
    if low == "pass":
        return "P"
    if low == "xx":
        return "XX"
    if low == "x":
        return "X"
    # bid: level + suit glyph or NT, e.g. "1NT", "3♥"
    m = re.match(r"^([1-7])\s*(NT|[♠♥♦♣])", t)
    if not m:
        raise ValueError(f"unrecognized call: {text!r}")
    level, suit = m.group(1), m.group(2)
    strain = "NT" if suit == "NT" else SUIT_GLYPH[suit]
    return f"{level}{strain}"


def parse_hand(text: str) -> str:
    """'♠ K J 7 2 ♥ T 8 ...' -> 'KJ72.T8.76.T8652' (♠.♥.♦.♣, '-'=void)."""
    compact = re.sub(r"\s+", "", text)
    m = re.search(
        r"♠(.*?)♥(.*?)♦(.*?)♣(.*)$", compact
    )
    if not m:
        raise ValueError(f"unparseable hand cell: {text!r}")
    suits = []
    for g in m.groups():
        cards = "".join(ch for ch in g if ch in CARD_CHARS)
        suits.append(cards if cards else "-")
    return ".".join(suits)


def hand_card_count(hand: str) -> int:
    return sum(0 if s == "-" else len(s) for s in hand.split("."))


# --- auctions ---------------------------------------------------------------

@dataclass
class Auction:
    contract: str            # normalized, e.g. '3H', 'Pass' (passed out)
    calls: list[str]         # dealer-first, real calls only: ['P','2S','2NT',...]
    first_seat: str          # seat of the first real call (must equal dealer)


def parse_auction(anchor: Node) -> Auction:
    """Parse one `<a class="tooltip">` auction (SPEC 4.4).

    Columns are always W N E S; skip the header row, read row-major, drop
    placeholders. The first real call belongs to the dealer.
    """
    # contract = the anchor's own text, before the hidden span/table
    span = anchor.css_first("span")
    contract_raw = anchor.text(deep=True)
    if span is not None:
        contract_raw = contract_raw.replace(span.text(deep=True), "")
    contract = _normalize_contract(contract_raw)

    table = anchor.css_first("span table")
    rows = table.css("tr")
    calls: list[str] = []
    first_seat: str | None = None
    for tr in rows[1:]:  # row 0 is the W/N/E/S header
        for col, td in enumerate(tr.css("td")):
            tok = normalize_call(td.text())
            if tok is None:
                continue
            if first_seat is None:
                first_seat = SEAT_ORDER[col % 4]
            calls.append(tok)
    return Auction(contract=contract, calls=calls, first_seat=first_seat or "")


def _normalize_contract(text: str) -> str:
    t = _ws(text)
    if not t:
        return ""
    if t.lower().startswith("pass"):
        return "Pass"
    m = re.match(r"^([1-7])\s*(NT|[♠♥♦♣])\s*(x{0,2})", t, re.I)
    if not m:
        return t
    strain = "NT" if m.group(2) == "NT" else SUIT_GLYPH[m.group(2)]
    return f"{m.group(1)}{strain}{m.group(3).lower()}"


def auction_complete(calls: list[str]) -> bool:
    """Complete = 4 passes total, or ends with 3 passes after a bid (SPEC 4.4)."""
    if calls == ["P", "P", "P", "P"]:
        return True
    return len(calls) >= 4 and calls[-3:] == ["P", "P", "P"] and any(
        c not in ("P", "X", "XX") for c in calls
    )


# --- deal diagram (BoardAcross) ---------------------------------------------

@dataclass
class Deal:
    board_no: int
    dealer: str              # 'N'/'E'/'S'/'W'
    vul: str                 # 'NONE'/'NS'/'EW'/'ALL'
    hand_n: str
    hand_w: str
    hand_e: str
    hand_s: str

    def all_cards_ok(self) -> bool:
        cards: list[str] = []
        for h in (self.hand_n, self.hand_e, self.hand_s, self.hand_w):
            for suit_i, s in enumerate(h.split(".")):
                if s == "-":
                    continue
                cards.extend(f"{suit_i}{c}" for c in s)
        return len(cards) == 52 and len(set(cards)) == 52


_VUL_MAP = {"None": "NONE", "N-S": "NS", "E-W": "EW", "All": "ALL"}
_DEALER_MAP = {"North": "N", "East": "E", "South": "S", "West": "W"}


def parse_deal_header(text: str) -> tuple[int, str, str]:
    """'Board 1. Dealer North. None Vulnerable.' -> (1, 'N', 'NONE')."""
    t = _ws(text)
    m = re.search(
        r"Board\s+(\d+)\.\s*Dealer\s+(\w+)\.\s*(.*?)\s*Vulnerable", t
    )
    if not m:
        raise ValueError(f"unparseable board header: {text!r}")
    return int(m.group(1)), _DEALER_MAP[m.group(2)], _VUL_MAP[m.group(3)]


@dataclass
class BoardAcross:
    deal: Deal
    auctions: list[Auction] = field(default_factory=list)


def parse_boardacross(raw: bytes | str) -> BoardAcross:
    """Parse a BoardAcross.asp page: deal diagram + every table's auction."""
    tree = HTMLParser(decode(raw))
    cells = tree.css(".BrdDispl")
    if len(cells) < 5:
        raise ValueError("expected >=5 BrdDispl cells (header + N,W,E,S hands)")
    board_no, dealer, vul = parse_deal_header(cells[0].text())
    # SPEC 4.3: DOM order after header is N, W, E, S
    hand_n = parse_hand(cells[1].text())
    hand_w = parse_hand(cells[2].text())
    hand_e = parse_hand(cells[3].text())
    hand_s = parse_hand(cells[4].text())
    deal = Deal(board_no, dealer, vul, hand_n, hand_w, hand_e, hand_s)
    auctions = [parse_auction(a) for a in tree.css("a.tooltip")]
    return BoardAcross(deal=deal, auctions=auctions)


# --- handsacross (all round deals, no auctions) -----------------------------

_HA_VUL = {"None": "NONE", "N-S": "NS", "E-W": "EW", "All": "ALL",
           "Both": "ALL", "Love": "NONE"}


def parse_handsacross(raw: bytes | str) -> list[Deal]:
    """Parse handsacross.asp: all deal diagrams for a round, no auctions.

    Header cells read like 'Brd 1N/None' (board, dealer, vul); the four
    BrdDispl cells that follow are the hands in N, W, E, S order.
    """
    tree = HTMLParser(decode(raw))
    hands = tree.css(".BrdDispl")
    # Header labels 'Brd N<Dealer>/<Vul>' are split across tags in the raw HTML,
    # so match against the whitespace-normalized rendered text.
    text = _ws(tree.css_first("body").text())
    headers = re.findall(
        r"Brd\s*(\d+)\s*([NESW])\s*/\s*(None|N-S|E-W|All|Both|Love)", text
    )
    deals: list[Deal] = []
    for i, (bno, dealer, vul) in enumerate(headers):
        base = i * 4
        if base + 3 >= len(hands):
            break
        n = parse_hand(hands[base + 0].text())
        w = parse_hand(hands[base + 1].text())
        e = parse_hand(hands[base + 2].text())
        s = parse_hand(hands[base + 3].text())
        deals.append(Deal(int(bno), dealer, _HA_VUL[vul], n, w, e, s))
    return deals


# --- RoundTeams -------------------------------------------------------------

@dataclass
class RoundMatch:
    ext_match_id: int
    home_team: str
    visiting_team: str
    home_team_id: int | None
    visiting_team_id: int | None


@dataclass
class RoundTeams:
    title: str
    matches: list[RoundMatch]
    team_ids: list[int]
    handsacross_href: str | None
    boardacrossfullround_href: str | None


def _href(node: Node) -> str:
    return node.attributes.get("href") or ""


def parse_roundteams(raw: bytes | str) -> RoundTeams:
    tree = HTMLParser(decode(raw))
    title = _ws(tree.css_first("body").text())[:120]
    match_ids: list[int] = []
    team_ids: list[int] = []
    handsacross = boardacross_full = None
    for a in tree.css("a"):
        href = _href(a)
        low = href.lower()
        if "boarddetails.asp" in low:
            m = re.search(r"qmatchid=(\d+)", href)
            if m:
                match_ids.append(int(m.group(1)))
        elif "teamdetails.asp" in low:
            m = re.search(r"qteamid=(\d+)", href)
            if m:
                team_ids.append(int(m.group(1)))
        elif "handsacross" in low:
            handsacross = href
        elif "boardacrossfullround" in low:
            boardacross_full = href
    # match ids appear once per BoardDetails link; preserve order, dedup
    seen: set[int] = set()
    ordered_matches = [m for m in match_ids if not (m in seen or seen.add(m))]
    matches = [
        RoundMatch(ext_match_id=mid, home_team="", visiting_team="",
                   home_team_id=None, visiting_team_id=None)
        for mid in ordered_matches
    ]
    return RoundTeams(
        title=title,
        matches=matches,
        team_ids=sorted(set(team_ids)),
        handsacross_href=handsacross,
        boardacrossfullround_href=boardacross_full,
    )


# --- BoardDetails -----------------------------------------------------------

@dataclass
class Seating:
    # room -> {seat: name}
    open: dict[str, str]
    closed: dict[str, str]


@dataclass
class BoardDetails:
    seating: Seating
    n_tooltips: int
    auctions: list[Auction]


def parse_seating(tree: HTMLParser) -> Seating:
    """Locate the Open/Closed name block (SPEC 4.5) and read the three name rows."""
    def nonempty(tr: Node) -> list[str]:
        return [c for c in (_ws(td.text()) for td in tr.css("td")) if c]

    header = None
    for tr in tree.css("tr"):
        if nonempty(tr) == ["Open Room", "Closed Room"]:
            header = tr
            break
    if header is None:
        raise ValueError("could not find Open Room / Closed Room header row")
    parent = header.parent
    sibs = [s for s in parent.iter() if s.tag == "tr"]
    idx = sibs.index(header)
    r1 = nonempty(sibs[idx + 1])  # [Open-N, Closed-N]
    r2 = nonempty(sibs[idx + 2])  # [Open-W, Open-E, Closed-W, Closed-E]
    r3 = nonempty(sibs[idx + 3])  # [Open-S, Closed-S]
    open_room = {"N": r1[0], "W": r2[0], "E": r2[1], "S": r3[0]}
    closed_room = {"N": r1[1], "W": r2[2], "E": r2[3], "S": r3[1]}
    return Seating(open=open_room, closed=closed_room)


def parse_boarddetails(raw: bytes | str) -> BoardDetails:
    tree = HTMLParser(decode(raw))
    seating = parse_seating(tree)
    tips = tree.css("a.tooltip")
    auctions = [parse_auction(a) for a in tips]
    return BoardDetails(seating=seating, n_tooltips=len(tips), auctions=auctions)
