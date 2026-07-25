"""One-off: fetch the eight M0 fixture pages and stage them under tests/fixtures/.

Run from a residential connection (SPEC 4.6). Idempotent: cached pages are reused.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from fetch import CACHE_ROOT, Fetcher

RIGA_BASE = "https://db.eurobridge.org/repository/competitions/26riga/microsite/Asp/"
HERNING_BASE = "http://db.worldbridge.org/Repository/tourn/Herning.25/microSite/Asp/"

REPO_ROOT = Path(__file__).resolve().parent.parent
FIX = REPO_ROOT / "tests" / "fixtures"

# (site, tournid, base, url_suffix, fixture_subdir, fixture_name)
JOBS = [
    ("EBL", "2620", RIGA_BASE, "BoardAcross.asp?qboard=001.01..2620", "riga", "boardacross_001.01..2620.html"),
    ("EBL", "2620", RIGA_BASE, "RoundTeams.asp?qtournid=2620&qroundno=1", "riga", "roundteams_r1.html"),
    ("EBL", "2620", RIGA_BASE, "BoardDetails.asp?qmatchid=158726", "riga", "boarddetails_158726.html"),
    ("EBL", "2620", RIGA_BASE, "handsacross.asp?qtournid=2620&qround=1", "riga", "handsacross_r1.html"),
    ("WBF", "2550", HERNING_BASE, "BoardAcross.asp?qboard=001.01..2550", "herning", "boardacross_001.01..2550.html"),
    ("WBF", "2550", HERNING_BASE, "RoundTeams.asp?qtournid=2550&qroundno=1", "herning", "roundteams_r1.html"),
    ("WBF", "2550", HERNING_BASE, "BoardDetails.asp?qmatchid=153334", "herning", "boarddetails_153334.html"),
    ("WBF", "2550", HERNING_BASE, "handsacross.asp?qtournid=2550&qround=1", "herning", "handsacross_r1.html"),
]


def main() -> None:
    with Fetcher() as fetcher:
        for site, tournid, base, suffix, subdir, name in JOBS:
            cache_path = CACHE_ROOT / site / tournid / name
            print(f"fetch {base}{suffix}")
            data = fetcher.get(base + suffix, cache_path)
            dest = FIX / subdir / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(cache_path, dest)
            print(f"  -> {len(data)} bytes -> {dest.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
