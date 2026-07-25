"""Given any microsite URL, find its Asp base, site, and the tournids of every
team series in that championship (SPEC 8.5). WBF siblings share one microsite
with different tournids; EBL likewise. Probes RoundTeams r1 per tournid."""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

from fetch import CACHE_ROOT, Fetcher
import parse


def parse_url(url: str):
    """-> (site, base, tournid|None). base ends at '/Asp/' (case preserved)."""
    m = re.search(r"^(.*?/[Aa]sp/)", url)
    base = m.group(1) if m else (url if url.endswith("/") else url + "/")
    low = url.lower()
    site = "EBL" if "eurobridge" in low else "WBF" if "worldbridge" in low else None
    q = parse_qs(urlsplit(url).query)
    tid = None
    if "qtournid" in q:
        tid = int(q["qtournid"][0])
    elif "qboard" in q:
        mm = re.search(r"\.\.(\d+)", q["qboard"][0])
        tid = int(mm.group(1)) if mm else None
    return site, base, tid


def series_from_title(title: str) -> str:
    m = re.search(r"Round\s*\d+\s+(.*?)\s+(?:Table|Home Team|There is no)", title)
    return (m.group(1).strip() if m else title[:60])


def discover(url: str, span: int = 12):
    """Probe tournids [tid-span, tid+span] for team events on this microsite."""
    site, base, tid = parse_url(url)
    if not (site and base and tid):
        raise ValueError(f"could not parse site/base/tournid from {url!r}")
    found = []
    with Fetcher() as f:
        for t in range(max(1, tid - span), tid + span + 1):
            u = f"{base}RoundTeams.asp?qtournid={t}&qroundno=1"
            cp = CACHE_ROOT / site / str(t) / "roundteams_r1.html"
            try:
                rt = parse.parse_roundteams(f.get(u, cp))
                if rt.matches:
                    found.append({"tournid": t, "matches": len(rt.matches),
                                  "series": series_from_title(rt.title),
                                  "site": site, "base": base})
            except Exception:
                pass
    return site, base, found
