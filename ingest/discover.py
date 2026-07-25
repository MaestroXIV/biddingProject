"""Given any microsite URL, find its Asp base, site, and the tournids of every
team series in that championship (SPEC 8.5). WBF siblings share one microsite
with different tournids; EBL likewise. Probes RoundTeams r1 per tournid."""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urljoin, urlsplit

from selectolax.parser import HTMLParser

from fetch import CACHE_ROOT, Fetcher
import parse


def _site_of(url: str) -> str | None:
    low = url.lower()
    return "EBL" if "eurobridge" in low else "WBF" if "worldbridge" in low else None


def _tid_of_href(href: str) -> int | None:
    q = parse_qs(urlsplit(href).query)
    if "qtournid" in q:
        return int(q["qtournid"][0])
    if "qboard" in q:
        mm = re.search(r"\.\.(\d+)", q["qboard"][0])
        return int(mm.group(1)) if mm else None
    return None


def seeds_from_url(url: str, fetcher: Fetcher):
    """Return (site, base, [seed tournids]) for any microsite URL.

    Handles a direct Asp URL, or a Results.htm-style landing page (fetched, then
    its Asp links mined for the real base and every linked series tournid)."""
    site = _site_of(url)
    if "/asp/" in url.lower():
        m = re.search(r"^(.*?/[Aa]sp/)", url)
        return site, m.group(1), [t for t in [_tid_of_href(url)] if t]
    # landing page: fetch and mine Asp links
    key = re.sub(r"\W+", "_", url)[-70:]
    raw = fetcher.get(url, CACHE_ROOT / (site or "X") / "_index" / f"{key}.html")
    html = raw.decode("iso-8859-1", "replace")
    base, tids = None, set()
    for a in HTMLParser(html).css("a"):
        href = a.attributes.get("href") or ""
        if ".asp" not in href.lower():
            continue
        absu = urljoin(url, href)
        m = re.search(r"^(.*?/[Aa]sp/)", absu)
        if m:
            base = m.group(1)
        t = _tid_of_href(absu)
        if t:
            tids.add(t)
    return site, base, sorted(tids)


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


def _probe(fetcher, site, base, tids):
    found = []
    for t in sorted(set(tids)):
        u = f"{base}RoundTeams.asp?qtournid={t}&qroundno=1"
        try:
            rt = parse.parse_roundteams(
                fetcher.get(u, CACHE_ROOT / site / str(t) / "roundteams_r1.html"))
            if rt.matches:
                found.append({"tournid": t, "matches": len(rt.matches),
                              "series": series_from_title(rt.title),
                              "site": site, "base": base})
        except Exception:
            pass
    return found


def discover(url: str, span: int = 8, fetcher: Fetcher | None = None):
    """Find a championship's base + team-series tournids from any of its URLs.

    Seeds from links on the landing page (or the URL's own tournid), then also
    probes a ±span window to catch series not linked on the page."""
    own = fetcher or Fetcher()
    try:
        site, base, seeds = seeds_from_url(url, own)
        if not (site and base):
            raise ValueError(f"could not resolve base for {url!r}")
        cand = set(seeds)
        for s in seeds:
            cand.update(range(s - span, s + span + 1))
        if not seeds:                       # no tournids linked: nothing to anchor on
            raise ValueError(f"no series tournids found on {url!r}")
        return site, base, _probe(own, site, base, cand)
    finally:
        if fetcher is None:
            own.close()
