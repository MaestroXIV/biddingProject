# Format notes — empirical findings

Running log of what the pages actually look like as we meet them (SPEC 8, 11.6).

## M1 ingest results (2026-07-25)

Both proving events crawled to `data/rawcache` and ingested. `bb stats`:

| Tournament | rounds | matches | deals | instances | auctions |
|---|---|---|---|---|---|
| Riga 2026 (EBL 2620) | 29 | 435 | 464 | 13,920 | 13,920 |
| Herning 2025 (WBF 2550) | 23 | 276 | 322 | 7,700 | 7,700 |

- **Riga matches every §10 golden exactly** (29 / 435 / 464 / 13,920). Integrity
  checks (52 cards/deal, opener=dealer-consistent, full seating per instance)
  **all pass**.
- **Kalita–Klukowski opened 1♣ on 61 Riga boards (Kalita 34, Klukowski 27)** —
  exact §10 match; first instance R1 Closed West Klukowski. Validates the whole
  chain (seating → player identity → pair key → opener derivation).
- **New Herning full-event goldens** (were unmeasured in §10): **23 rounds,
  12 matches/round (276), 14 boards/round → 322 deals, 7,700 instances.**
  Riga is perfectly uniform (all 464 deals × 30 tables). Herning is uniform at
  24 instances/deal (308 deals) except **14 deals in one round have 22** — one
  match there is short two tables (a not-played/absent BoardDetails, a normal
  real-world gap). 308×24 + 14×22 = 7,700. Integrity still passes.

**Cross-tournament player identity works:** Kalita & Klukowski also play Herning
(Bermuda Bowl), and exact-alias merge (SPEC 5) unifies them across events — so
pair/opening queries must scope by tournament when reproducing a per-event
golden. This is intended behaviour, not a bug.

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

**UPDATE (2026-07-25): it is not just the IP.** From Gregor's own residential
Mac, `httpx` still gets a **403 whose body is the Cloudflare "Just a moment…"
JavaScript challenge** (`just a moment` / `enable javascript` / `cloudflare`
markers), even with a full browser-plausible header set. Only a real browser
that executes the challenge JS gets through. Plain HTTP clients (`httpx`,
`curl`) cannot fetch EBL at all right now. Per SPEC 4.6 / 11.6 we do **not**
try to solve the challenge — that is circumvention.

**How the Riga fixtures were actually obtained (M0):** opened each of the four
URLs in a normal browser (challenge passes for real), then File → Save As →
HTML-only into `tests/fixtures/riga/`. Committed. All 6 Riga goldens pass.
`decode()` now tries UTF-8 first (browsers re-encode on save) then falls back to
iso-8859-1; suit symbols are HTML entities so they survive either way.

**⚠ Consequence for M1 (EBL ingest, ~490 pages):** the `httpx`-based
`fetch.py` works for WBF but **cannot fetch EBL** while this challenge is up.
`fetch_fixtures.py` / `ingest --site EBL` will 403 on every page. Before M1 can
ingest Riga we need one of: (a) a browser-driven fetch (e.g. Playwright, which
runs the JS and yields real bytes), or (b) reuse a `cf_clearance` cookie copied
from Gregor's solved browser session (fragile: ~30 min TTL, must match UA+IP).
Flag to Gregor — this is a scope change to the fetch layer, not a parser issue.

## Auction / hand parsing — as specified (SPEC 4.3–4.5), verified on WBF

- Auction columns are always **W N E S**; skip the header row, read row-major,
  drop `-`/blank placeholder cells. First real call belongs to the dealer
  (asserted per auction).
- Calls normalized to `P`, `X`, `XX`, `1C…7NT`. Suit glyphs → `S/H/D/C`.
- Seating block on `BoardDetails`: the `Open Room / Closed Room` header row is
  followed by three name rows (`[N,N]`, `[W,E,W,E]`, `[S,S]`), SPEC 4.5.
- Pages decode as **iso-8859-1**.
