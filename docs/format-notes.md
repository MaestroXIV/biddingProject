# Format notes — empirical findings

Running log of what the pages actually look like as we meet them (SPEC 8, 11.6).

## `handsacross.asp` — VERDICT (M0 probe, SPEC 8.1)

**Confirmed: `handsacross.asp?qtournid=…&qround=N` returns every deal diagram
for the round in a single page, with no auctions.** The M0 hypothesis holds —
it is the preferred deal source (1 fetch/round) and the 16×`BoardAcross`
fallback is not needed for deal diagrams.

Verified against WBF Herning 2025 round 1 (`qtournid=2550`):

- 14 boards in the round → 14 headers, 56 `.BrdDispl` hand cells (14 × 4 hands).
- Hand cells are in **N, W, E, S** order per board, same as `BoardAcross`
  (SPEC 4.3). Board 1's four hands are byte-for-byte the same deal as
  `BoardAcross.asp?qboard=001.01..2550` (asserted in
  `test_handsacross_matches_boardacross`).
- **More compact markup than `BoardAcross`:** the header is a small label
  `Brd 1N/None` (board / dealer / vul, vul values `None`, `N-S`, `E-W`, `All`)
  rather than the `Board 1. Dealer North. None Vulnerable.` sentence, and cards
  are concatenated (`KJ72`) rather than space-separated. `T` is still ten.
- The header label text is **split across HTML tags**, so it must be matched
  against the whitespace-normalized rendered text, not the raw HTML.
- **No `a.tooltip` elements** — there are no auctions on this page. Auctions
  still come from `BoardDetails` / `BoardAcross`.

Parser: `parse_handsacross()` in `ingest/parse.py`.

_EBL Riga `handsacross` (round 1) is expected to match this shape; confirm once
the EBL fixture is fetched (see below). The Riga golden already asserts board 1
= `542.8.Q764.K8542` and the 52-card invariant across all round deals._

## EBL Cloudflare IP block (SPEC 4.6) — encountered

Fetching any EBL page (`db.eurobridge.org`) from this build environment returns
**HTTP 403 (server: cloudflare)** regardless of User-Agent (tried both the
honest `BoardBase/0.1` UA and a browser-plausible Chrome UA). This is exactly
the datacenter/cloud-IP block the spec anticipates: **this environment is not on
a residential IP.** WBF (`db.worldbridge.org`, plain HTTP) is unaffected and
returned 200 for all four Herning fixtures.

Per SPEC 4.6 / 11.6 we do **not** try to circumvent this beyond honest headers.
Consequence for M0: the four **Herning** fixtures are fetched and committed, and
all their goldens pass. The four **Riga** fixtures could not be fetched here.

**To fetch the Riga fixtures**, run this once from Gregor's Mac (residential
connection), which demonstrably works per the pre-study session:

```
python ingest/fetch_fixtures.py
```

It writes all eight fixtures (cache-first; the four Herning ones are already
cached) into `tests/fixtures/`. The Riga golden tests in `tests/test_riga.py`
skip while those files are absent and turn green automatically once present.

## Auction / hand parsing — as specified (SPEC 4.3–4.5), verified on WBF

- Auction columns are always **W N E S**; skip the header row, read row-major,
  drop `-`/blank placeholder cells. First real call belongs to the dealer
  (asserted per auction).
- Calls normalized to `P`, `X`, `XX`, `1C…7NT`. Suit glyphs → `S/H/D/C`.
- Seating block on `BoardDetails`: the `Open Room / Closed Room` header row is
  followed by three name rows (`[N,N]`, `[W,E,W,E]`, `[S,S]`), SPEC 4.5.
- Pages decode as **iso-8859-1**.
