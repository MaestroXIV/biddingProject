"""Given any microsite URL, find its Asp base, site, and the tournids of every
series in that championship (SPEC 8.5, PAIRS_KO.md §3).

- A landing page (Results.htm style): every linked qtournid is classified by
  the page it links to (TotalPairs -> pairs, Knockoutphase* -> ko,
  RoundTeams -> teams) and named from one fetched page (`discover_landing`).
- A direct Asp URL: the classic teams probe of RoundTeams r1 over a +-span
  window of tournids (`discover`).
WBF siblings share one microsite with different tournids; EBL likewise."""
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


# --- landing-page classification (PAIRS_KO.md §3) -------------------------------

_KIND_PRIORITY = ("ko", "pairs", "teams")


def kind_of_href(href: str) -> str | None:
    """Tournament kind implied by the page a link points to, else None."""
    page = urlsplit(href).path.rsplit("/", 1)[-1].lower()
    if page.startswith("totalpairs"):
        return "pairs"
    if page.startswith("knockoutphase"):
        return "ko"
    if page.startswith("roundteams"):
        return "teams"
    return None


def _is_alt_view(href: str) -> bool:
    """RunningScores/Asp/*Condit* pages: alternative views of the same tournid."""
    low = urlsplit(href).path.lower()
    return "runningscores" in low or "condit" in low.rsplit("/", 1)[-1]


def classify_landing(html: str, url: str) -> tuple[str | None, list[dict]]:
    """Classify every qtournid linked from a landing page by its linked page.

    Returns (base, [{tournid, kind, href, text}]) sorted by tournid. A tournid's
    RunningScores/*Condit* links are ignored when it has a plain Asp link; a
    tournid linked only to unclassifiable pages is dropped."""
    base = alt_base = None
    links: dict[int, list[tuple[bool, str, str, str]]] = {}
    for a in HTMLParser(html).css("a"):
        href = a.attributes.get("href") or ""
        if ".asp" not in href.lower():
            continue
        absu = urljoin(url, href)
        alt = _is_alt_view(absu)
        m = re.search(r"^(.*?/[Aa]sp/)", absu)
        if m:
            if alt:
                alt_base = alt_base or m.group(1)
            else:
                base = base or m.group(1)
        tid = _tid_of_href(absu)
        kind = kind_of_href(absu)
        if tid is None or kind is None:
            continue
        text = re.sub(r"\s+", " ", a.text() or "").strip()
        links.setdefault(tid, []).append((alt, kind, absu, text))
    out = []
    for tid in sorted(links):
        ls = links[tid]
        plain = [x for x in ls if not x[0]]
        use = plain or ls
        kinds = {k for _, k, _, _ in use}
        kind = next(k for k in _KIND_PRIORITY if k in kinds)
        _, _, href, text = next(x for x in use if x[1] == kind)
        out.append({"tournid": tid, "kind": kind, "href": href, "text": text})
    return base or alt_base, out


def _on_base(base: str, href: str) -> str:
    """Re-anchor a link's page+query on the plain Asp base."""
    sp = urlsplit(href)
    page = sp.path.rsplit("/", 1)[-1]
    return f"{base}{page}" + (f"?{sp.query}" if sp.query else "")


def _teams_name(raw: bytes) -> tuple[str | None, int]:
    """Event name + match count of a RoundTeams r1 page (classic or cards)."""
    html = parse.decode(raw)
    tree = HTMLParser(html)
    sel = (tree.css_first("select.phase-sel option[selected]")
           or tree.css_first("select option[selected]"))
    rt = parse.parse_roundteams(raw)
    name = None
    if sel is not None and sel.text().strip():
        name = re.sub(r"\s+", " ", sel.text()).strip()
    else:
        s = series_from_title(rt.title)
        if s and s != rt.title[:60]:
            name = s
    return name, len(rt.matches)


def name_entries(entries: list[dict], site: str, base: str,
                 fetcher: Fetcher) -> list[dict]:
    """Fill entry['name'] (and 'matches' for teams) by fetching one page each.

    pairs: TotalPairs event dropdown; ko: Knockoutphase dropdown name minus
    ' - <phase>'; teams: RoundTeams event / title. Falls back to the landing
    link text. Never fatal."""
    pair_names: dict[int, str] = {}
    for e in entries:
        tid, kind, name = e["tournid"], e["kind"], None
        d = CACHE_ROOT / site / str(tid)
        try:
            if kind == "pairs":
                if tid not in pair_names:
                    raw = fetcher.get(_on_base(base, e["href"]), d / "discover_tp.html")
                    pair_names.update(parse.parse_pairs_event_names(raw))
                name = pair_names.get(tid)
            elif kind == "ko":
                raw = fetcher.get(_on_base(base, e["href"]), d / "discover_ko.html")
                phases = parse.parse_ko_phases(raw, tid)
                if phases:
                    name = phases[0].name.rsplit(" - ", 1)[0].strip()
            else:
                raw = fetcher.get(
                    f"{base}RoundTeams.asp?qtournid={tid}&qroundno=1",
                    d / "roundteams_r1.html")
                name, e["matches"] = _teams_name(raw)
        except Exception as ex:
            e["error"] = f"{ex.__class__.__name__}: {ex}"
        e["name"] = name or e.get("text") or f"{kind} {tid}"
    return entries


def discover_landing(url: str, fetcher: Fetcher):
    """-> (site, base, [{tournid, kind, name, ...}]) for a Results.htm-style page."""
    site = _site_of(url)
    key = re.sub(r"\W+", "_", url)[-70:]
    raw = fetcher.get(url, CACHE_ROOT / (site or "X") / "_index" / f"{key}.html")
    base, entries = classify_landing(parse.decode(raw), url)
    if not base:
        raise ValueError(f"could not resolve base for {url!r}")
    if not entries:
        raise ValueError(f"no classifiable series links on {url!r}")
    return site, base, name_entries(entries, site or "X", base, fetcher)


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "event"


def plan_registrations(entries: list[dict], site: str, base: str, year: int,
                       prefix: str) -> list:
    """Tournament rows for discovered entries: key = <prefix>_<slug>.

    KO events get a '_ko' slug suffix (their name usually equals the teams
    qualifier's); remaining collisions get '_<tournid>'."""
    from registry import Tournament
    out, used = [], set()
    for e in sorted(entries, key=lambda x: x["tournid"]):
        event = e["name"]
        slug = slugify(event) + ("_ko" if e["kind"] == "ko" else "")
        key = f"{prefix}_{slug}"
        if key in used:
            key = f"{key}_{e['tournid']}"
        used.add(key)
        label = f"{event} KO" if e["kind"] == "ko" else event
        out.append(Tournament(key=key, site=site, base=base, tournid=e["tournid"],
                              name=f"{label} {year}", year=year, series=event,
                              kind=e["kind"]))
    return out
