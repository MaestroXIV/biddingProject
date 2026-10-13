# Pairs, knockout and the 2026 "cards" layout — design contract

Architect's contract for extending BoardBase beyond classic round-robin teams.
Goal: `bb` can ingest **every** series of a WBF/EBL championship such as the
2026 World Bridge Series in Katowice (teams Swiss/RR, teams knockout, pairs),
and the UI/offline file shows them sensibly. Existing events and all existing
tests must keep working unchanged.

Verified 2026-10-13 against the live Katowice microsite
(`http://db.worldbridge.org/Repository/tourn/Katowice.26/microSite/Asp/`).

## 1. What the site looks like (verified facts)

Katowice uses a redesigned page family ("cards" layout). Classic selectors
(`a.tooltip`, `.BrdDispl`, "Open Room | Closed Room" rows) are **absent** on every
Katowice page — including plain teams `BoardDetails.asp`. Older events (Herning
2025, Riga 2026 …) stay classic. One parser per page type, auto-detecting layout.

| Page | Used for | Layout notes |
|---|---|---|
| `RoundTeams.asp?qtournid=T&qroundno=R` | teams round: match list | `div.match[data-mid]`, `a.tbl-link` → `BoardDetails.asp?qmatchid=M&qdesktop=0`, `.m-team.home/.vis a.name` → `TeamDetails.asp?qteamid=N` |
| `BoardDetails.asp?qmatchid=M` | teams match: lineups + every board both rooms | `.matchhead .team.home/.vis`, `.lineups .lineup` (h4 Open/Closed Room, `.pos-n/.pos-w/.pos-e/.pos-s .pn`), `div.board-card` per board: `.brd` (`Brd 1`, href qboard), `.room.open/.room.closed` each with `.cell.contract` (`4♥` + `span.decl`), `.cell.lead .cv`, `.cell.tricks .cv`, `.cell.score .cv.score` (`sc-home`/`sc-vis`), and `.bidpanel .bidcol` (one table per room: `.bidcol-h` "Open Room"/"Closed Room") |
| `BoardDetailsKO.asp?qmatchid=M&qphase=P` | KO segment | identical to BoardDetails (plus an `imps` class); team links point to knockoutphase (no team id) |
| `handsacross.asp` / `HandsAcrossKO.asp?qtournid=T&qround=SEG&qphase=P` / `HandsAcrossPairs.asp` | deals | `div.deal-card`: `.dc-brd` (board no), `.dc-info` "Dealer **North** / **None** vulnerable", `.deal .pos-n/.pos-w/.pos-e/.pos-s .hand .row` (`♠ AKQ3`) |
| `Knockoutphase.asp?qtournid=T&qphase=P` | KO phase: segment match ids | `select` options `?qtournid=T&qphase=P…` list every phase of every KO event; links `BoardDetailsKO.asp?qmatchid=M&qphase=P` — one id per (match, segment) |
| `TotalPairs.asp?qtournid=T&qgroupno=G&qroundno=S` | pairs ranking | two `select.navsel`: phases of this event (`?qtournid=T&qgroupno=G&qroundno=LAST…` + name: Final / SemiFinal A / SemiFinal B / Qualifier, most significant first) and events (also bare `?qtournid=…` options, spanning every pairs tournid; on BoardAcrossPairs pages the event options start `TotalPairs.asp?`) |
| `BoardAcrossPairs.asp?qboard=B&qtournid=T&qroundno=S&qgroupno=G&qdesktop=0` | **pairs traveller — the only pairs page we need** | `.bh-title` "Board 1", `.bh-sub` "Dealer **North** • **None** Vulnerable", `.deal` diagram (cards space-separated `Q 4`, void `–`), `select.brd-sel` options = every board of the session; `div.board-card` per table: `.tblno` "Tbl 1", `.dirchip` "Sec 1", `.pr-cell.ns a[href*=qpairid]` + `.nfull` ×2, `.px-cell.ns .mpv/.pcv`, same for `.ew`, `.cell.contract` (`6♦` + `span.decl`), `.cell.score .cv` (`sc-ns`/`sc-ew`), `.cell.lead`, `.cell.tricks`, optional `.bidpanel` (one table) |

Edge cases seen (Open Pairs qualifier session 1: 16 boards × 96 tables, 12 sections):
- 16 of 96 tables per board have **no `.bidpanel`** (no auction recorded) → instance stored, no auction row.
- contract `Adj.` (adjusted score, e.g. `+20`, lead/tricks `&nbsp;`, a bogus all-pass bidpanel) → contract `Adj`, **no auction row**.
- contract `Pass` (passed out, score `0`, real 4-pass bidpanel) → contract `Pass`, scores (0, 0), auction `P P P P`.
- contract text may lack the space before the declarer (`4♥N`) or include doubling (`4♥x E`).
- `.pcv` can be blank (`" "`) → None.
- Score cell: the value is signed **from N-S's point of view** and the class says which side gained (`sc-ns`/`sc-ew`, teams: `sc-home`/`sc-vis`). Store the classic convention: `score_ns = v if v > 0`, `score_ew = -v if v < 0`, `v == 0` → (0, 0).
- Out-of-range board/session → ~770-byte empty shell (no `.board-card`, no `.bh-title`) → `EmptyPage`.
- Entities: fixtures were saved through a trimmer (scripts/svg/img/comments removed, whitespace collapsed) — raw pages are bigger but structurally identical. Suits appear as `&hearts;` entities or literal `♥`; parse rendered text, never raw HTML.

## 2. Data model (minimal change — every existing query keeps working)

New columns (schema.sql + `store.migrate()` adds them to old DBs in place):

| table | column | meaning |
|---|---|---|
| tournament | `kind` | `'teams'` / `'ko'` / `'pairs'` |
| round | `stage` | KO phase name / pairs phase name; NULL for teams |
| match | `seats_known` | 1 normally; **0 for pairs** (we know the pair's two players, not who sat N vs S) |
| board_instance | `mp_ns, mp_ew, pct_ns, pct_ew, table_label` | pairs only |

Mapping per kind:

- **teams** (classic or cards): unchanged. Layout dispatch happens inside the parsers.
- **ko**: one `round` per (phase, segment): `number = phase_index*100 + segment` (phase_index = 1-based position in the KO dropdown for this tournid, earliest first), `label = "<phase name> · Seg <n>"`, `stage = <phase name>` (strip the event prefix: "Mixed Teams - Phase of 16" → "Phase of 16"). `team.ext_id` is synthetic (KO pages carry no team id): `-(zlib.crc32(name) & 0x7fffffff)` — stable across runs. `match` = one BoardDetailsKO page (one segment). Seating/instances exactly as teams. `deal.source_url = {base}BoardAcrossKO.asp?qboard=BBB.SS.P.T`.
- **pairs**: one `round` per (phase, session): `number = phase_index*100 + session` (phase_index: Qualifier = 1 … Final = last, i.e. play order), `label = "<phase> · Session <s>"`, `stage = <phase>`. A **pair is a `team` row**: `ext_id = qpairid`, `name = "SURNAME1 – SURNAME2"`. `match` = one (round, NS pair, EW pair) meeting: `ext_match_id = ns_pair_id*100000 + ew_pair_id`, `home = NS pair`, `visiting = EW pair`, `seats_known = 0`. One `room = 'Open'` per match. Seating: N = first listed NS player, S = second, E = first EW, W = second (order as listed — **not** real seats). `board_instance` gets mp/pct/table_label (`"Sec 3 Tbl 7"`). `deal.source_url = {base}BoardAcrossPairs.asp?qboard=B&qtournid=T&qroundno=S&qgroupno=G`.
- **derive**: for `match.seats_known = 0`, `auction.opener_player_id = NULL` (player-level attribution would be a guess); `instance_side.pair_key` still correct (unordered pair) so all pair queries work.

## 3. Crawl flows (cache names under `data/rawcache/{site}/{tournid}/`)

Polite and cache-first as today (`Fetcher.get`, 1 req/s). Never refetch a cached page.

- **teams**: unchanged (`roundteams_r{R}.html`, `boarddetails_{M}.html`, `handsacross_r{R}.html`).
- **ko**: `ko_entry.html` = `Knockoutphase.asp?qtournid=T&qphase=<first that works of FF,SF,QF,16,32,64>` → `parse_ko_phases` → for each phase P: `ko_phase_{P}.html` → `parse_ko_match_ids` → `bdko_{M}.html` (`BoardDetailsKO.asp?qmatchid=M&qphase=P`) → segments from `BoardDetails.segment` → `hako_{P}_r{SEG}.html` (`HandsAcrossKO.asp?qtournid=T&qround=SEG&qphase=P`).
- **pairs**: `tp_entry.html` = `TotalPairs.asp?qtournid=T&qgroupno=<first that yields phases of 1,2,6,7,8,3,4,5>&qroundno=1` → `parse_pairs_phases` → for each phase G, session S in 1..last_session: `bap_g{G}_r{S}_b{B}.html`, starting with the session's first board (B = 1; if EmptyPage try the TotalPairs session page's first `BoardAcrosspairs` link) and continuing through `board_hrefs`. Missing session (EmptyPage on its first board) → skip.

`bb discover <landing-url>` learns pairs and KO: classify every `qtournid` found on the landing page by the page it links to (`TotalPairs` → pairs, `Knockoutphase`/`KnockoutphaseConditStat…` → ko, `RoundTeams.asp` → teams), name it (pairs: event dropdown name; ko: dropdown name minus " - <phase>"; teams: RoundTeams title/series), and with `--register --year Y --prefix P` register them all (`key = P_<slug>`). `bb ingest` accepts glob keys (`bb ingest 'katowice26_*'`).

Katowice 2026 series (from the landing page): pairs 2644 Open, 2645 Women, 2646 Senior, 2647 Mixed, 2671 Pairs First Week, 2676 WBF Cup, 2677 President's Cup; ko 2650 Open, 2651 Women, 2652 Senior, 2653 Mixed; teams/Swiss/BAM 2640–2643, 2648, 2649, 2654–2659, 2672–2675, 2679. Pages linked through `RunningScores/Asp/*Condit*` are alternative views of the same tournids — ignore them.

## 4. Ownership (parallel build — edit only your files)

| Worker | Owns | Builds |
|---|---|---|
| **P (parsers)** | `ingest/parse.py` (the cards/pairs/KO section at the bottom + layout dispatch at the top of `parse_roundteams`, `parse_handsacross`, `parse_boarddetails`), `tests/test_katowice_parse.py` | every function in the contract section; classic behaviour byte-for-byte unchanged |
| **S (pipeline)** | `ingest/crawl.py`, `ingest/store.py`, `ingest/derive.py`, `ingest/integrity.py`, `ingest/discover.py`, `ingest/cli.py`, `ingest/registry.py`, `tests/test_pipeline_pairs_ko.py` | §2/§3 for ko + pairs, discover/register, glob ingest |
| **W (web)** | `web/**`, `share/app.html`, `share/build.py`, `tests/test_web_pairs.py` | UI for pairs/KO in both the server app and the offline file |

The architect owns `db/schema.sql`, `docs/`, the contract dataclasses, and integration.

## 5. Fixtures (`tests/fixtures/katowice/`, trimmed real pages)

| file | content | goldens |
|---|---|---|
| `boardacrosspairs_2646_g2_r1_b1.html` | Senior Pairs qualifier S1 board 1, all 13 tables | dealer N, vul NONE, N `Q4.Q652.QJ4.AQJ4`, S `KJ975.-.AK765.KT2`; 16 board hrefs; table 1: Sec 1 Tbl 1, NS 3014 (ANKIERSZTEJN Andrzej, BARYLA Zdzislaw) mp 22.00 / 91.67%, EW 3001 (KULPINSKI Dariusz, KRUCZEK Boguslaw) mp 2.00 / 8.33%, `6D` by S, lead `HA`, 12 tricks, score_ns 920, auction `1C 2D X P 2NT P 3S P 3NT P 4D P 5D P 6D P P P` (first seat N); contracts of the 13 tables: 6D S, 3Hx E, 3NT N, 4S S, 6D S, 4S S, 5D S, 4H E, 3NT N, 4S S, 3NT N, 6D N, 4S S; scores_ns +920 +300 +430 +480 +920 +450 +420 +150 −150(→ score_ew 150) +480 +520 +920 +480; 0 tables without auction |
| `boardacrosspairs_2644_g2_r1_b2_excerpt.html` | Open Pairs Q S1 board 2, 4 of 96 tables | contracts `4H` N, `4H` N, `Adj` (score_ns 20, no auction, lead '', tricks None), `4H` N **without bidpanel** |
| `boardacrosspairs_2644_g2_r1_b12_excerpt.html` | Open Pairs Q S1 board 12, 4 tables | `4Hx` E, `3S` N (score_ew 100), `Pass` (scores 0/0, auction P P P P), `3S` N without bidpanel |
| `boarddetails_163531.html` | Senior Swiss R1 table 61, MILNER (3001) v VALLON (3002), 14 boards | 28 instances; open: N TUSZYNSKI Piotr, W BERENDREGT Carel, E IJSSELMUIDEN Peter, S KOWALSKI Apolinary; closed: N VAN DER NEUT Jaap, W MILNER Reese, E LALL Hemant, S ZWART Peter; brd 1 open 4H N lead S7 11 tricks score_ns 450, auction `1NT P 4D P 4H P P P`; closed 4H N lead S6 13 tricks score_ns 510, auction `1NT P 2D P 2H P 4H P P P`; board 1 qboard `001.01..2642` |
| `roundteams_2642_r1.html` | Senior Swiss R1 match list | first match: id 163531, table 61, MILNER 3001 v VALLON 3002; handsacross href `handsacross.asp?qtournid=2642&qround=1` |
| `handsacross_2642_r1.html` | Senior Swiss R1 deals | board 1 dealer N vul NONE, N `AKQ3.A84.QJ5.J95`; board 2 dealer E vul NS; every deal 52 cards |

KO detail pages are structurally identical to `boarddetails_163531.html` (verified by class-set diff); KO phase pages are only regex-mined for ids.

## 6. Acceptance

1. Full suite green (old 34 + new).
2. Rebuilding the old DB from the old cache (`bb reparse`) is unchanged (same counts).
3. On fixtures: every golden in §5.
4. Synthetic end-to-end: a temp rawcache assembled from fixtures for one pairs session and one teams round goes through store → derive → integrity with no issues, and the web app renders a pairs deal (MP %, "Sec 1 Tbl 1", NS/EW pair names) and a teams deal.
5. Gregor's real run on his Mac: `bb discover <Katowice Results.htm> --register --year 2026 --prefix katowice26` then `bb ingest 'katowice26_*'` ends with "Integrity: ALL PASS".
