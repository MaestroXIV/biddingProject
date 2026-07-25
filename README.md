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
