"""Tournament registry (SPEC 3, 4.1). Store the full Asp base URL per
tournament and never construct it from parts -- path casing differs per site."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Tournament:
    key: str
    site: str            # 'EBL' | 'WBF'
    base: str            # full Asp base URL, trailing slash
    tournid: int
    name: str
    year: int
    series: str = ""


TOURNAMENTS = {
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
