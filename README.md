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

## M2 — browse UI

    .venv/bin/uvicorn app:app --app-dir web --reload

Then open http://127.0.0.1:8000 . Filter boards (tournament, player, pair,
opening call, position, vulnerability, competitive, contract…), click any card
to open the **deal traveller** (full diagram + every table's auction, filterable
by opening call), and follow the "source" links back to the official EBL/WBF
pages. "Export CSV" downloads the current result set.
