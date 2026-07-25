# BoardBase — Concept & Build Instructions

**A searchable database of tournament bridge boards from EBL and WBF championships, focused on reconstructing real bidding sequences.**

Version 1.0 · 2026-07-24 · Commissioned by Gregor · To be implemented by Claude (Opus/Sonnet) in Claude Code.
Working title "BoardBase" — rename freely.

---

## 0. How to use this document

**For Gregor:** create an empty git repository, put this file in it as `SPEC.md`, open Claude Code in that repo, and start with the kickoff prompt in §11. The implementer works milestone by milestone (§9) and shows you a demo at the end of each.

**For the implementing model:** this spec was produced after a working session in which the EBL microsite format was reverse-engineered empirically and a full event (Riga 2026, 13,920 auctions) was successfully scraped, parsed, and analyzed. §4 (source format) and §10 (golden test values) are *verified facts*, not guesses — treat mismatches with §10 as bugs in your code until proven otherwise. Everything else is design intent you may refine with good judgment. Your working agreement is §11.

---

## 1. Vision

Championship bridge today leaves a complete electronic record: every table, every deal, every call. The EBL (European Bridge League) and WBF (World Bridge Federation) publish these on identically-structured results microsites — but they are only browsable board by board, match by match. There is no way to ask questions across an event or across events.

BoardBase ingests those microsites into a local database and makes the auctions *queryable*, so a player can:

- pull up **every board where a given pair opened 1♣** and see the hands they did it with;
- explore what happened **after a given sequence start** (`1♣ – (1♠) – X …`) — what the next calls were, with what hands, how often;
- filter boards by player, pair, team, seat/position, vulnerability, opening bid, competitive vs uncontested, hand strength/shape;
- find **field-contested decisions** — boards where the field genuinely split on what to open or overcall;
- always link back to the official source page for any board.

**The goal is reconstruction, not ranking.** The site exists to let you *recreate sequences* — to reverse-engineer, from evidence, how a partnership actually bids: what their 1♣ is, what a given rebid showed, how they act over interference. It is explicitly **not** a tool for deciding "which system is best"; results/scores are stored as context, never as a leaderboard of systems.

### Non-goals (v1)

- No card-by-card play records (opening lead, tricks, and scores *are* captured from results tables; full play via `PlayDetails.asp` is a later milestone, §9 M6).
- No public deployment, accounts, or multi-user features. It runs locally on Gregor's Mac.
- No bidding-system inference AI. The site shows evidence; the human draws conclusions.
- No sources beyond the EBL/WBF microsite family (LoveBridge vugraph archives, BBO `.lin`, PBN imports are future ideas, §12).

---

## 2. Users and core use cases

Single user (Gregor — expert bridge player) plus occasionally his partner/teammates looking over his shoulder. Every use case below must be satisfiable in the v1 UI; treat them as acceptance scenarios:

1. **Pair openings**: "Show all boards from Riga 2026 where Kalita–Klukowski's side opened 1♣." → list of 61 boards (verified count, §10), each with the opener's hand, full auction, deal link. *(This reproduces a document built by hand in the pre-study session.)*
2. **Sequence explorer**: "For Kalita–Klukowski, after `1♣ (P) 1♥`, what did opener rebid?" → breakdown of next calls with counts, hand summaries per branch (HCP range, shapes), drill-down to boards.
3. **Cross-field comparison on one deal**: "Open deal Riga R1 board 1 and show me all 30 tables' auctions" → traveller view. "Now only the tables where East opened 2♥."
4. **Contested decisions**: "Across the event, which opening decisions split the field by more than 20% (min 10 tables)?" → 327 opening + 117 overcall decisions for Riga (verified, §10), sortable/filterable, exportable. *(Reproduces the spreadsheet built in the pre-study session.)*
5. **Player view**: "Every board Michał Klukowski played in Herning 2025, filterable to boards where he was the opener."
6. **Situational search**: "All auctions in the database that start `1NT (2♥)` where the next player held 8–11 HCP" → what did they do?
7. **Provenance**: from any board in any view, one click reaches the official `BoardAcross.asp` page it came from.

---

## 3. Decisions already made (with the commissioner)

| Question | Decision |
|---|---|
| Hosting | **Local-first.** A web app served on `localhost` on Gregor's Mac. Public deployment is a later possibility, not a v1 concern. This also sidesteps EBL's datacenter-IP blocking (§4.6) — the scraper runs from a residential IP that demonstrably works. |
| v1 data | **Two proving events**: EBL Riga 2026 (`26riga`, tournid **2620**) and WBF Herning 2025 Bermuda Bowl (`Herning.25`, tournid **2550**). Both formats exercised end to end. Further events are added one `ingest` command at a time. |
| Stack | **Python 3.11+**, SQLite, FastAPI + Jinja2 templates (+ htmx for interactivity if useful). One language, no build step, runs with one command. Parsing with `selectolax` or BeautifulSoup; HTTP with `httpx`. |
| Play data | **Auctions only in v1.** Lead/tricks/scores captured from results tables. `PlayDetails` card play is milestone M6. |

---

## 4. The data source: the EBL/WBF microsite format (verified)

Both federations run the same ASP results software. One parser family handles both; only the base URL differs.

### 4.1 Base URLs and the two proving events

| | EBL Riga 2026 | WBF Herning 2025 (Bermuda Bowl) |
|---|---|---|
| Base | `https://db.eurobridge.org/repository/competitions/26riga/microsite/Asp/` | `http://db.worldbridge.org/Repository/tourn/Herning.25/microSite/Asp/` |
| tournid | `2620` | `2550` |
| Teams | 30 (round robin, 29 rounds × 16 boards) | 24 (round robin; 12 matches/round) |
| Tables per deal | 30 (15 matches × Open + Closed room) | 24 (12 × 2) |
| Protocol quirk | HTTPS; **403s datacenter/cloud IPs** (Cloudflare) — fine from residential | Plain HTTP; **https:// 302-redirects to http://**; no blocking observed |

Path casing differs between sites (`repository/competitions/...` vs `Repository/tourn/...`) — store the full Asp base URL per tournament in the registry and never construct it from parts.

Parallel WBF series (Venice Cup, d'Orsi, Mixed) run on the **same microsite with different tournids**, not linked from within a series' own pages. Discovering their tournids (via the microsite home page) is an open probe (§8); the registry treats each series as its own tournament.

### 4.2 Page inventory (all relative to the Asp base)

| Page | Parameters | Contains | Role in ingest |
|---|---|---|---|
| `RoundTeams.asp` | `qtournid`, `qroundno` | The round's match list: per match a `BoardDetails.asp?qmatchid=` link, team names + `TeamDetails.asp?qteamid=` links, VP/IMP score. Also links `boardacrossfullround.asp` and `handsacross.asp` for the round. | Enumerate matches & teams per round |
| `BoardDetails.asp` | `qmatchid` | One match: **player names by room and seat** (§4.5), and for each of the 16 boards both rooms' rows — contract (tooltip = **full auction**, §4.4), declarer, lead, tricks, NS/EW scores, IMPs. | **Primary source** for seatings, auctions, results |
| `BoardAcross.asp` | `qboard=BBB.RR..TTTT` | One deal across the whole field: board header + **deal diagram** (§4.3) + every table's rows (auction tooltips, results). No player names. | Deal source (or cross-check); the canonical **provenance deep link** |
| `boardacrossfullround.asp` | `qtournid`, `qround` | All 16 boards' auctions for a round in one page (480 tooltips at Riga). **No deal diagrams.** | Optional bulk cross-check |
| `handsacross.asp` | `qtournid`, `qround` | Linked "hand records for the round" — almost certainly all 16 deal diagrams in one page. **Not yet parsed — verify in M0**; fallback is 16× `BoardAcross` (fully validated). | Preferred deal source (1 fetch/round) |
| `TeamDetails.asp` | `qteamid` | Team roster & results | Team/player metadata |
| `PlayDetails.asp` | `qboard`, `qtournid`, `qmatchid` | Card-by-card play. **Returned HTTP 500 on Riga during the session** — treat as unreliable; out of scope until M6. | Later |

**The `qboard` code**: `BBB.RR..TTTT` — zero-padded board (3), dot, zero-padded round (2), dot, an **empty middle field** (likely session/segment for KO matches — open question §8), dot, tournid. Example: `001.01..2620`. Board numbers repeat across rounds (Riga alternates 1–16 / 17–32 by round, but **not strictly** — R15 used 17–32) and **the deals differ every round**, so a deal is keyed by (tournament, round, board), never by board alone. Enumerate valid codes from the links on `boardacrossfullround.asp`/`RoundTeams.asp` rather than generating them blindly.

### 4.3 Deal diagram parsing (`BoardAcross.asp`, verified)

Cells with CSS class **`BrdDispl`** appear in DOM order: `[board header, North hand, West hand, East hand, South hand]` — i.e. hand order **N, W, E, S**.

- Header text: `Board 1. Dealer North. None Vulnerable.` → regex `Board\s+(\d+)\.\s*Dealer\s+(\w+)\.\s*(.*?)\s*Vulnerable`. Vulnerability values: `None`, `N-S`, `E-W`, `All`.
- Hands are four lines, one per suit in order ♠♥♦♣, suit glyphs as HTML entities (`&spades;` etc., hearts/diamonds wrapped in red `<font>` tags); cards as characters with **`T` for ten** (never `10`); a void renders as an empty suit line.
- Charset: pages declare `iso-8859-1` — decode accordingly (names like TURKIYE, MichaƂ variants; trust the HTTP/meta charset).

Sanity invariants to assert per deal: 4×13 = 52 cards, each exactly once.

### 4.4 Auction tooltip parsing (verified — identical on both sites)

Every contract cell is an `<a class="tooltip">` whose hidden `<span><table>` holds the full auction:

```html
<a href="#" class="tooltip">4<font color="#C01616">♥</font>
  <span><table>
    <tr align="center"><td><b>West</b></td><td><b>North</b></td><td><b>East</b></td><td><b>South</b></td></tr>
    <tr align="center"><td>-</td><td>Pass</td><td>1<font size="4">♥</font></td><td>Pass</td></tr>
    <tr align="center"><td>1<font size="4">♠</font></td><td>Pass</td><td>2<font size="4">♥</font></td><td>Pass</td></tr>
    <tr align="center"><td>4<font size="4">♥</font></td><td>Pass</td><td>Pass</td><td>Pass</td></tr>
  </table></span>
</a>
```

Parsing rules (all verified against 13,920 auctions):

- Column order is **always W, N, E, S** regardless of dealer. Skip the header row; read remaining rows row-major.
- `-` (or empty) = seat not yet on lead rotation (cells before the dealer in row 1, and trailing cells after the final pass). Skip them.
- The first real token always belongs to the **dealer** — assert this against the deal's dealer.
- Call encodings: `Pass` (case-insensitive), `x` = double, `xx` = redouble, bids as level + suit glyph or `NT` (e.g. `1NT`, `2NT`). Normalize to tokens `P`, `X`, `XX`, `1C`…`7NT`.
- A passed-out board is `P P P P`.
- Auctions may be incomplete on rare boards (adjusted/fouled); store what's there with a `complete` flag (complete = ends with 3 passes after a bid, or 4 passes total).

### 4.5 Player seating (`BoardDetails.asp`, verified)

After a 3-cell header row `['Open Room', '', 'Closed Room']`, three rows of names follow (filter out empty cells):

- row +1: `[Open-North, Closed-North]`
- row +2: `[Open-West, Open-East, Closed-West, Closed-East]`
- row +3: `[Open-South, Closed-South]`

Names are `SURNAME Firstname` (e.g. `KLUKOWSKI Michal`). Verified example — Riga R1, Switzerland v Croatia, `qmatchid=158726`: Open room N=MULTON Franck, W=DJILOVIC Josko, E=MIJIC Ante, S=ZIMMERMANN Pierre; Closed room N=VIDOVIC Toni, **W=KLUKOWSKI Michal, E=KALITA Jacek**, S=KATUSIC Filip.

Each board's two rows (Open, then Closed with a yellow-ish `bgcolor`) carry: contract tooltip (auction), declarer (`N/E/S/W`), lead (suit glyph + card), tricks, NS score, EW score, and match IMPs. Lineups can change between matches — parse seating **per match**, never assume continuity.

### 4.6 Fetching rules (binding)

- **Politeness**: max ~1 request/second, sequential, with an honest UA: `BoardBase/0.1 (personal research; gregor.rus14@gmail.com)`. These are static archives — there is never a reason to hammer them.
- **Cache-first, forever**: every fetched page is written to `data/rawcache/{site}/{tournid}/{name}.html` before parsing; re-ingest and re-parse must work **entirely from cache** with zero network. Parsing is pure (`html -> dataclasses`); fetching is a separate layer.
- **EBL blocks cloud IPs** (Cloudflare; observed 403s from a datacenter, success from a residential browser). The scraper runs on Gregor's Mac, so this should not bite; still send a browser-plausible `User-Agent` and treat 403 as "back off and tell the user", not "retry harder". Never attempt to circumvent beyond honest headers.
- WBF is plain HTTP (https redirects *to* http) — follow the redirect, don't force TLS.
- Fetch volume per teams event ≈ `rounds × (1 RoundTeams + matches BoardDetails + 1 handsacross)` — Riga ≈ 29 × 17 ≈ 490 requests ≈ 10 minutes at 1 r/s. Fine.
- Attribution: every deal page in the UI shows "Source: EBL/WBF" with the deep `BoardAcross` link.

---

## 5. Data model

SQLite, one file (`data/boardbase.db`). Scale check: Riga = 464 deals / 13,920 auction instances ≈ small; even 50 events ≈ a few hundred MB — SQLite is comfortably sufficient.

```sql
CREATE TABLE site        (id INTEGER PRIMARY KEY, code TEXT UNIQUE,          -- 'EBL' | 'WBF'
                          note TEXT);
CREATE TABLE tournament  (id INTEGER PRIMARY KEY, site_id INT REFERENCES site,
                          slug TEXT, tourn_code INT, name TEXT, series TEXT,
                          year INT, venue TEXT, asp_base_url TEXT,
                          ingested_at TEXT, UNIQUE(site_id, tourn_code));
CREATE TABLE team        (id INTEGER PRIMARY KEY, tournament_id INT, ext_id INT,
                          name TEXT, UNIQUE(tournament_id, ext_id));
CREATE TABLE player      (id INTEGER PRIMARY KEY, canonical_name TEXT, country TEXT);
CREATE TABLE player_alias(alias TEXT, player_id INT REFERENCES player,
                          PRIMARY KEY(alias, player_id));
CREATE TABLE round       (id INTEGER PRIMARY KEY, tournament_id INT, number INT,
                          label TEXT, UNIQUE(tournament_id, number));
CREATE TABLE match       (id INTEGER PRIMARY KEY, round_id INT, ext_match_id INT,
                          home_team_id INT, visiting_team_id INT,
                          UNIQUE(round_id, ext_match_id));
CREATE TABLE seating     (match_id INT, room TEXT CHECK(room IN ('Open','Closed')),
                          seat TEXT CHECK(seat IN ('N','E','S','W')),
                          player_id INT, PRIMARY KEY(match_id, room, seat));

CREATE TABLE deal        (id INTEGER PRIMARY KEY, round_id INT, board_no INT,
                          dealer TEXT, vul TEXT CHECK(vul IN ('NONE','NS','EW','ALL')),
                          hand_n TEXT, hand_e TEXT, hand_s TEXT, hand_w TEXT,  -- 'AKQ4.T82.7.J9532' (♠.♥.♦.♣, '-'=void)
                          source_url TEXT, UNIQUE(round_id, board_no));

CREATE TABLE board_instance (id INTEGER PRIMARY KEY, deal_id INT, match_id INT,
                          room TEXT, contract TEXT, declarer TEXT, lead TEXT,
                          tricks INT, score_ns INT, score_ew INT,
                          UNIQUE(deal_id, match_id, room));

CREATE TABLE auction     (board_instance_id INT PRIMARY KEY REFERENCES board_instance,
                          calls TEXT,            -- absolute, dealer first: 'P 1C P 1H ...'
                          complete INT,
                          opener_seat TEXT, opener_rel_pos INT,   -- 1..4 from dealer
                          opening_call TEXT, opener_player_id INT,
                          opening_side TEXT CHECK(opening_side IN ('NS','EW')),
                          competitive INT,       -- 1 if the non-opening side ever acted (bid/X/XX)
                          vul_rel TEXT CHECK(vul_rel IN ('none','both','fav','unfav')),  -- relative to opening side
                          from_opener TEXT,      -- canonical: '1C (P) 1H (P) 2NT ...'
                          uncontested_key TEXT); -- defender passes stripped: '1C 1H 2NT ...'; NULL if competitive
CREATE INDEX ix_auction_open   ON auction(opening_call, opener_player_id);
CREATE INDEX ix_auction_seq    ON auction(from_opener);
CREATE INDEX ix_auction_unc    ON auction(uncontested_key);

CREATE TABLE instance_side (board_instance_id INT, side TEXT CHECK(side IN ('NS','EW')),
                          player_lo INT, player_hi INT,          -- ordered pair of player ids
                          pair_key TEXT,                          -- 'lo-hi' for pair filtering
                          PRIMARY KEY(board_instance_id, side));
CREATE INDEX ix_side_pair ON instance_side(pair_key);

CREATE TABLE hand_feature (deal_id INT, seat TEXT, hcp INT, shape TEXT,   -- '5-3-3-2' in ♠♥♦♣ order
                          pattern TEXT,          -- sorted lengths '5332'
                          balanced INT, longest_suit TEXT,
                          PRIMARY KEY(deal_id, seat));

CREATE TABLE decision    (id INTEGER PRIMARY KEY, deal_id INT, seat TEXT,
                          kind TEXT CHECK(kind IN ('open','overcall')),
                          context_opening TEXT,  -- the exact opening faced (overcall rows only)
                          n INT, dist TEXT,      -- JSON [['1H',21],['2H',6],...]
                          top_call TEXT, alt_share REAL);
```

Notes:

- **Player identity**: store the raw `SURNAME Firstname` string as an alias; canonical player created on first sight of a new alias. Cross-tournament merging is automatic only on exact alias match; anything fuzzier (diacritics, initials) is a manual admin action. Conservative beats clever here.
- **`vul_rel`** encodes vulnerability relative to the opening side (`fav` = they're NV vs V) — that's how players actually think about preempt/overcall filters.
- **Derived rows** (`auction` derived columns, `hand_feature`, `instance_side`, `decision`) are recomputed by a `reparse`/`derive` step that reads only the DB + cache, never the network.

## 6. Canonical auction notation (the search key)

Storage/search tokens: `P`, `X`, `XX`, `1C 1D 1H 1S 1NT … 7NT`. The UI renders suit symbols (♥♦ red) but URLs/queries/storage use letters.

Two canonical strings per auction, both starting at the **opening bid** (everything before it is preserved in `calls` + `opener_rel_pos`):

- **`from_opener`** — every call in order; the defending side's calls in parentheses:
  `1C (P) 1H (P) 1NT (P) 2H (X) P (P) …`
- **`uncontested_key`** — only defined when the defenders never acted (all their calls were passes): defender passes stripped:
  `1C 1H 1NT 2H` · `NULL` for competitive auctions.

Search semantics: a query without parentheses (`1C 1H`) is a **prefix match on `uncontested_key`** — "show me this uncontested start". A query with parentheses (`1C (1S) X`) is a prefix match on `from_opener`. Both are index-friendly `LIKE 'prefix%'`. No wildcards in v1 — the Sequence Explorer's next-call faceting (§7.3) covers exploration better than wildcards would.

## 7. The product (v1 pages)

Visual conventions everywhere: suits as symbols with ♥♦ in red; deal diagrams in the classic N/W-E/S cross layout; auction tables with W-N-E-S columns aligned from dealer exactly like the source sites; the opening bid highlighted. (The pre-study session produced a docx with this styling — match its spirit.)

### 7.1 Search / browse (home)

One filter bar over `board_instance ⋈ auction ⋈ deal`: tournament, round range, team, player (any seat / opener only), **pair** (unordered, on opening side / either side), position (1st–4th), dealer, vulnerability (absolute or `vul_rel`), opening call, sequence prefix (§6), competitive y/n, final contract, declarer side, opener HCP range, opener shape/pattern. Results as compact board cards: deal mini-info, opener hand, auction one-liner, contract/result, links. Pagination; CSV export of any result set.

### 7.2 Deal page (traveller)

The full deal diagram + every table's row (teams, room, auction rendered from the tooltip data, contract, declarer, lead, tricks, scores) with the two source deep links (`BoardAcross`, `BoardDetails`). Filter rows by opening call to see field splits at a glance.

### 7.3 Sequence Explorer — the heart of the site

Input: any filter set from 7.1 (typically a pair) + a sequence prefix. Output:

- **N auctions match.** Breakdown of the **next call**: e.g. after `1C (P) 1H` → `1NT ×9 · 2C ×5 · 1S ×4 · …`, each branch clickable to extend the prefix (this *is* the bidding-tree navigation).
- Per branch: hand summary of the player who made that call — HCP min/median/max, common shapes — and the list of boards behind it.
- Breadcrumb of the prefix so far; one click back to any earlier node.

This is how "recreate their system after the 1♣ opening" actually happens: walk the tree, read the hands at each node.

### 7.4 Pair & player pages

Openings dashboard for a pair: frequency grid of opening calls by position × vulnerability; entry points into the Sequence Explorer pre-filtered to the pair; list of events they appear in. Player page: same, single player, plus which pairs they've played in.

### 7.5 Contested decisions

The generalized 20% tool from the pre-study session: per (deal, seat) opening decisions and per (deal, seat, opening-faced) direct overcall decisions across the field, with sliders for min tables (default 10) and alternative-share threshold (default 20%). Table view mirroring the session's spreadsheet columns; CSV export. Note in the UI that splits can be systemic (strong club vs natural, Multi vs weak two) rather than judgment.

### 7.6 Ingest (CLI + thin admin page)

```
bb ingest --site EBL --base https://db.eurobridge.org/repository/competitions/26riga/microsite/Asp/ --tournid 2620 --name "European Open Teams 2026" --year 2026
bb ingest --site WBF --base http://db.worldbridge.org/Repository/tourn/Herning.25/microSite/Asp/ --tournid 2550 --name "Bermuda Bowl 2025" --year 2025
bb derive        # recompute all derived tables from the DB
bb reparse       # re-run parsers over the raw HTML cache (no network)
bb stats         # row counts per tournament, integrity check results
```

Ingest flow per tournament: enumerate rounds from `RoundTeams.asp` (increment `qroundno` until empty) → per round fetch `RoundTeams` + each `BoardDetails` + `handsacross` (fallback: per-board `BoardAcross`) → parse → insert → derive → run integrity checks (§9 M1 DoD). Idempotent: re-running skips cached fetches and upserts.

The admin page is just a form that shells out to the same code with a progress log.

## 8. Known unknowns (probe when first needed, document in `docs/format-notes.md`)

1. `handsacross.asp` content — expected: all 16 deal diagrams per round. Verify in M0; fallback (`BoardAcross` ×16) is fully validated.
2. The empty middle field of `qboard` (`001.01..2620`) — probably session/segment for KO-stage matches. Both proving events are round robins; probe when ingesting a KO stage.
3. KO / Swiss stage page shapes (same `RoundTeams.asp`? different?). Out of v1 scope; the registry's `series` field is where stages land.
4. Pairs tournaments (different page family, e.g. Butler/MP travellers). Out of v1 scope.
5. WBF parallel-series tournids (Venice Cup, d'Orsi, Mixed at Herning) — discover via microsite home when wanted.
6. Older microsites (pre-~2015) may differ in markup; ingest is per-event, so handle variants as they're met, never speculatively.
7. `PlayDetails.asp` 500s observed on Riga — retest on Herning at M6.

## 9. Milestones

Work strictly in order; each ends with a demo to Gregor and the DoD checked.

**M0 — Parsers with golden tests (no DB, no UI).**
Fetch once and commit as fixtures: Riga `BoardAcross 001.01..2620`, `RoundTeams r1`, `BoardDetails 158726`, `handsacross r1`; Herning `BoardAcross 001.01..2550`, `RoundTeams r1`, one `BoardDetails`, `handsacross r1`. Pure parse functions + pytest.
*DoD: every §10 golden value asserted green; 52-card and dealer-first invariants enforced; `handsacross` verdict written to `docs/format-notes.md`.*

**M1 — Schema + ingest of both proving events.**
*DoD: `bb stats` shows Riga: 29 rounds, 435 matches, 464 deals, 13,920 board instances with auctions; Herning: 12 matches/round, 24 instances/deal, full-event counts recorded and spot-checked against the live site; integrity checks (52 cards/deal; auction starts at dealer; instance↔seating consistency) pass at 100% or discrepancies are listed and explained.*

**M2 — Browse UI.**
Home filters (tournament, player, pair, opening, competitive, vul, position) + results list + deal/traveller page with correct rendering and provenance links.
*DoD: use-cases 1, 3, 5, 7 of §2 demonstrably work.*

**M3 — Sequence search + Explorer.**
Canonical strings computed for all auctions; prefix search; Explorer with next-call faceting and per-branch hand summaries.
*DoD: use-cases 2 and 6 work; `Kalita–Klukowski + opening 1C` returns exactly the 61 boards of §10.*

**M4 — Pair/player dashboards.** Opening frequency grids, event lists.
*DoD: use-case 5 one click from a player page; K–K dashboard shows 34/27 opener split for 1♣ at Riga.*

**M5 — Contested analytics.**
*DoD: Riga with defaults (≥10 tables, >20%) yields exactly 327 opening + 117 overcall decisions; sliders re-derive live; CSV export matches the session spreadsheet's columns.*

**M6+ (backlog, unscheduled)** — `PlayDetails` card play; more events via registry; KO stages; pairs events; docx/xlsx export of filtered board sets (reproducing the session's two artifacts); PBN export; public deployment.

## 10. Golden test values (verified in the pre-study session — regression anchors)

**EBL Riga 2026 (base §4.1, tournid 2620):**

- `RoundTeams r1`: 15 matches; includes Switzerland v Croatia `qmatchid=158726`, Italy v Poland `158739`, Romania v Latvia `158729`.
- Event shape: 29 rounds × 16 boards; per-round board numbers are 1–16 or 17–32 (not strictly alternating — R15 is 17–32); 30 tables per deal; 464 deals; 13,920 auctions.
- `BoardAcross.asp?qboard=001.01..2620`: header `Board 1. Dealer North. None Vulnerable.`; 30 auction tooltips; hands (♠.♥.♦.♣): N `542.8.Q764.K8542` (5 HCP), E `J87.KQT763.KJT.9` (10), S `AT3.A942.A93.Q73` (14), W `KQ96.J5.852.AJT6` (11).
- Board 1 first-call tallies: North (1st seat): Pass ×29, 3C ×1. East (2nd seat, n=29): 1H ×21, 2H ×6, 2D ×2. South over 1H (n=21): Pass ×18, X ×3.
- `boardacrossfullround r1`: 480 tooltips, 0 deal diagrams.
- `BoardDetails 158726` seating: Open N/S = MULTON Franck / ZIMMERMANN Pierre, W/E = DJILOVIC Josko / MIJIC Ante; Closed N/S = VIDOVIC Toni / KATUSIC Filip, **W = KLUKOWSKI Michal, E = KALITA Jacek**. 32 auction tooltips (16 boards × 2 rooms). Closed-room board 4 auction begins `W:1C`.
- Kalita–Klukowski (Switzerland, all 29 rounds): boards where their side's opening bid was 1♣: **61** (Kalita 34, Klukowski 27); opener HCP range 10–26; first instance R1 board 4 (Klukowski, West, Closed).
- Contested-decision analysis (min 10 tables, top call < 80%): **327 opening + 117 overcall** decisions; opening-decision groups with n≥10: 792; overcall groups with n≥10: 522.

**WBF Herning 2025 Bermuda Bowl (base §4.1, tournid 2550):**

- `RoundTeams r1`: header "47th World Teams Championships" / Bermuda Bowl; 12 matches; `BoardDetails qmatchid` range 153334–153345; `TeamDetails qteamid` 1001–1024; same `boardacrossfullround` and `handsacross` links as EBL.
- `BoardAcross.asp?qboard=001.01..2550`: header `Board 1. Dealer North. None Vulnerable.`; 12 table rows / 24 auction tooltips; North hand `KJ72.T8.76.T8652`; `PlayDetails.asp` links present.
- (Herning full-event counts were not measured in the session — record them at M1 ingest and add them here as goldens.)

## 11. Working agreement for the implementing model

1. **Read this spec fully before writing code.** §4 and §10 are verified ground truth; when your parser disagrees with §10, your parser is wrong until you can show the site itself changed.
2. Repo layout: `ingest/` (fetch, cache, parsers, normalize, derive, CLI), `web/` (FastAPI app + templates + static), `db/schema.sql`, `tests/` (fixtures + goldens), `docs/format-notes.md` (your empirical findings as you meet variants), `SPEC.md` (this file).
3. **TDD the parsers**: commit fixture HTML first, write goldens from §10, then code to green. Parsers are pure functions; no network in tests.
4. **Politeness rules of §4.6 are binding.** Never crawl beyond the registered tournaments. Ask Gregor before any fetch burst beyond an event ingest (~500 requests).
5. Milestones in order; stop at each DoD and demo. Do not gold-plate ahead of the milestone.
6. When reality diverges from the spec (page variant, missing page, new event type): probe minimally, write what you find in `docs/format-notes.md`, and ask Gregor if it changes scope.
7. Keep everything re-runnable offline: cache → parse → derive is deterministic; `bb reparse` must rebuild the DB from cache alone.
8. UI text and rendering follow §7's conventions; keep the UI plain, fast, and dense — this is a study tool, not a marketing site.
9. Names, encodings: decode per page charset; normalize whitespace; store raw name as alias verbatim; be conservative about merging identities (§5).
10. The commissioner is an expert bridge player and a non-expert developer: explain choices briefly in plain language, and surface anything ambiguous as a question rather than a silent assumption.

**Kickoff prompt for Gregor to paste into Claude Code:**

> Read SPEC.md in this repository completely, then implement milestone M0 exactly as specified: create the repo layout from §11.2, fetch the eight fixture pages listed in M0 (politely, per §4.6), commit them under tests/fixtures/, and build the parsers with pytest goldens from §10. Stop when M0's definition of done is green and show me the test output and what you learned about handsacross.asp.

## 12. Later ideas (out of scope, recorded so they aren't lost)

Card play ingest and a play viewer; LoveBridge vugraph archives as a second source family (confirmed to expose deals via `https://vugraph.lovebridge.com/api/archive/boards/...`; auctions live behind a separate endpoint that was not mapped); BBO `.lin` import; PBN import/export; double-dummy par via a DDS binding to annotate decisions; shareable read-only deployment for teammates; saved searches; a "quiz mode" that hides the field's choice on contested decisions until you answer.

---

*Format knowledge in §4 and all values in §10 were established empirically on 2026-07-23/24 against the live EBL Riga 2026 and WBF Herning 2025 microsites.*
