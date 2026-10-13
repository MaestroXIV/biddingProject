"""Tournament registry (SPEC 3, 4.1). Store the full Asp base URL per
tournament and never construct it from parts -- path casing differs per site.

Built-in proving events live here; user-added events are appended to
data/tournaments.json and merged in at import (so `bb ingest --base ...` events
persist across runs)."""
from __future__ import annotations

import fnmatch
import json
from dataclasses import asdict, dataclass
from pathlib import Path

KINDS = ("teams", "ko", "pairs")
USER_REGISTRY = Path(__file__).resolve().parent.parent / "data" / "tournaments.json"


@dataclass(frozen=True)
class Tournament:
    key: str
    site: str            # 'EBL' | 'WBF'
    base: str            # full Asp base URL, trailing slash
    tournid: int
    name: str
    year: int
    series: str = ""
    kind: str = "teams"  # 'teams' (RoundTeams) | 'ko' (Knockoutphase) | 'pairs' (TotalPairs)


_BUILTIN = {
    "riga": Tournament(
        key="riga", site="EBL",
        base="https://db.eurobridge.org/repository/competitions/26riga/microsite/Asp/",
        tournid=2620, name="European Open Teams 2026", year=2026,
        series="Open Teams",
    ),
    "herning": Tournament(
        key="herning", site="WBF",
        base="http://db.worldbridge.org/Repository/tourn/Herning.25/microSite/Asp/",
        tournid=2550, name="Bermuda Bowl 2025", year=2025,
        series="Bermuda Bowl",
    ),
}


def _load_user() -> dict:
    if not USER_REGISTRY.exists():
        return {}
    data = json.loads(USER_REGISTRY.read_text())
    # entries written before 'kind' existed load as 'teams' (dataclass default)
    return {d["key"]: Tournament(**d) for d in data}


def register(t: Tournament) -> None:
    """Persist a user-added tournament to data/tournaments.json (idempotent)."""
    if t.kind not in KINDS:
        raise ValueError(f"unknown tournament kind {t.kind!r} (expected {KINDS})")
    existing = []
    if USER_REGISTRY.exists():
        existing = [d for d in json.loads(USER_REGISTRY.read_text())
                    if d["key"] != t.key]
    existing.append(asdict(t))
    USER_REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    USER_REGISTRY.write_text(json.dumps(existing, indent=2))
    TOURNAMENTS[t.key] = t


TOURNAMENTS = {**_BUILTIN, **_load_user()}


def select_keys(patterns: list[str], keys=None) -> list[str]:
    """Expand registry keys / shell-style globs ('katowice26_*') in order.

    Plain keys must exist; a glob that matches nothing is an error too (a typo
    should not silently ingest nothing). Duplicates are dropped."""
    pool = list(TOURNAMENTS if keys is None else keys)
    out: list[str] = []
    for pat in patterns:
        if any(ch in pat for ch in "*?["):
            hits = [k for k in pool if fnmatch.fnmatchcase(k, pat)]
        else:
            hits = [pat] if pat in pool else []
        if not hits:
            raise KeyError(f"no registered tournament matches {pat!r}")
        out.extend(h for h in hits if h not in out)
    return out
