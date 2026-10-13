# BoardBase

Searchable database of tournament bridge auctions from EBL/WBF microsites.
See `SPEC.md` for the full concept and milestones.

## Setup

    python3.12 -m venv .venv
    .venv/bin/pip install -r requirements.txt

## M0 — parsers + golden tests

Pure parsers for the four page types live in `ingest/parse.py`; fetching (polite,
cache-first, SPEC 4.6) is in `ingest/fetch.py`. Run the goldens:

    .venv/bin/python -m pytest tests/ -q

WBF Herning fixtures are committed and green. EBL Riga fixtures must be fetched
from a residential connection (EBL 403s cloud IPs — see `docs/format-notes.md`):

    .venv/bin/python ingest/fetch_fixtures.py

The Riga golden tests skip until those fixtures exist, then pass automatically.

## Adding more events

Every event is one `ingest` command. New WBF events are quick (plain HTTP); EBL
events open your real Chrome once for the Cloudflare check.

    .venv/bin/python ingest/cli.py list
    .venv/bin/python ingest/cli.py ingest --site WBF \
        --base http://db.worldbridge.org/Repository/tourn/Herning.25/microSite/Asp/ \
        --tournid 2551 --name "Venice Cup 2025" --year 2025 --series "Venice Cup"

The event is remembered in `data/tournaments.json`. WBF parallel series share a
microsite with different tournids (Herning: Bermuda Bowl 2550, Venice Cup 2551,
d'Orsi 2552, Wuhan Cup 2553).

## M2 — browse UI

    .venv/bin/uvicorn app:app --app-dir web --reload

Then open http://127.0.0.1:8000 . Filter boards (tournament, player, pair,
opening call, position, vulnerability, competitive, contract…), click any card
to open the **deal traveller** (full diagram + every table's auction, filterable
by opening call), and follow the "source" links back to the official EBL/WBF
pages. "Export CSV" downloads the current result set.

## Share as a single offline file

Build a self-contained `BoardBase.html` — the whole database runs inside the
browser via SQLite-WebAssembly, so search / Explorer / dashboards all work with
no server and no internet:

    .venv/bin/python share/build.py      # -> dist/BoardBase.html (~17 MB)

Send that one file to anyone; they double-click it to open in a modern browser
(Chrome/Edge/Firefox/Safari). Nothing to install.

## Pairs and knockout events

The browse UI and the offline file show all three event kinds; the tournament
dropdown marks them (`… · pairs`, `… · KO`), and a **Stage** filter (Qualifier,
Final, Phase of 16 …) appears once the DB has staged rounds.

- **KO**: rendered like teams (Open/Closed rooms, seats), but the round shows
  its label (`Phase of 16 · Seg 2`) wherever teams events show `R3`.
- **Pairs**: each result is one table — `Sec 1 Tbl 1 · NS pair vs EW pair` —
  with the board's matchpoints and percentage for NS and EW instead of rooms;
  rounds show `Qualifier · Session 3`. Pair names link to the pair dashboard.
  The auction header shows no player names, because who sat N vs S inside a
  pair isn't published.
- Tables without a recorded auction (or with an adjusted score, `Adj`) still
  appear in the traveller with a muted "no bidding recorded"; searches that
  filter on the auction naturally skip them.
- **Player** opener counts cover teams/KO only (pairs events count at pair level
  only — a note says so). The **Pair** dashboard includes pairs events; those
  openings land in a separate **pair** column.

The UI works on old and migrated DBs alike. `BOARDBASE_DB=/path/to.db` points
the server at another DB; `share/build.py --db X --out Y` builds the offline
file from any DB.
