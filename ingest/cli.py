"""`bb` command-line interface (SPEC 7.6, PAIRS_KO.md §3).

    bb ingest [keys...]   crawl (network) then parse+store+derive+integrity;
                          keys may be globs: bb ingest 'katowice26_*'
    bb ingest --site EBL --base <AspURL> --tournid N --name "..." --year Y
              [--series "..."] [--key slug] [--kind teams|ko|pairs]
                          register + ingest a NEW event (default kind: teams)
    bb discover <url> [span] [--register --year Y --prefix P]
                          landing page (Results.htm): list every series with
                          its kind (teams/ko/pairs) and name; --register adds
                          them all as P_<slug>. Direct Asp URL: probe teams
                          series in a +-span tournid window (default 8).
    bb reparse [keys...]  rebuild DB from the raw cache only (no network)
    bb derive             recompute derived tables from the DB
    bb stats              row counts per tournament + integrity check
    bb list               show registered tournaments
"""
from __future__ import annotations

import argparse
import re
import sys

import crawl
import derive as derive_mod
import integrity
import store
from registry import KINDS, TOURNAMENTS, Tournament, register, select_keys


def _register_from_flags(argv: list[str]) -> str:
    p = argparse.ArgumentParser(prog="bb ingest", add_help=False)
    p.add_argument("--site", required=True, choices=["EBL", "WBF"])
    p.add_argument("--base", required=True)
    p.add_argument("--tournid", required=True, type=int)
    p.add_argument("--name", required=True)
    p.add_argument("--year", required=True, type=int)
    p.add_argument("--series", default="")
    p.add_argument("--key", default=None)
    p.add_argument("--kind", default="teams", choices=list(KINDS))
    a = p.parse_args(argv)
    base = a.base if a.base.endswith("/") else a.base + "/"
    key = a.key or re.sub(r"[^a-z0-9]+", "-",
                          f"{a.name}-{a.year}".lower()).strip("-")
    t = Tournament(key=key, site=a.site, base=base, tournid=a.tournid,
                   name=a.name, year=a.year, series=a.series, kind=a.kind)
    register(t)
    print(f"registered '{key}': {a.name} ({a.site} {a.tournid}, {a.kind})")
    return key


def _cached_keys() -> list[str]:
    out = []
    for key, t in TOURNAMENTS.items():
        if crawl.cache_path(t, crawl.entry_cache_name(t)).exists():
            out.append(key)
    return out


def _expand(keys: list[str]) -> list[str]:
    try:
        return select_keys(keys)
    except KeyError as e:
        print(f"error: {e.args[0]}  (see `bb list`)")
        sys.exit(2)


def cmd_ingest(keys: list[str]) -> None:
    if any(a.startswith("--") for a in keys):     # new event by flags
        keys = [_register_from_flags(keys)]
    keys = _expand(keys) if keys else list(TOURNAMENTS)
    ok = []
    with crawl.Fetcher() as fetcher:
        for key in keys:
            print(f"=== crawling {key} ({TOURNAMENTS[key].kind}) ===", flush=True)
            try:
                print(f"    {crawl.crawl(TOURNAMENTS[key], fetcher)}", flush=True)
                ok.append(key)
            except Exception as e:     # one broken event must not stop the rest
                print(f"=== {key} FAILED: {e.__class__.__name__}: {e} ===",
                      flush=True)
    if not ok:
        print("nothing crawled successfully; DB unchanged")
        return
    cmd_reparse(ok)


def cmd_list(_keys: list[str]) -> None:
    for key, t in TOURNAMENTS.items():
        print(f"  {key:16} {t.site} {t.tournid} {t.kind:5}  {t.name} ({t.year})")


def cmd_discover(args: list[str]) -> None:
    import discover as disc
    p = argparse.ArgumentParser(prog="bb discover")
    p.add_argument("urls", nargs="+")
    p.add_argument("--register", action="store_true")
    p.add_argument("--year", type=int)
    p.add_argument("--prefix")
    a = p.parse_args(args)
    if a.register and not (a.year and a.prefix):
        p.error("--register needs --year and --prefix")
    urls = [u for u in a.urls if not u.isdigit()]
    span = next((int(u) for u in a.urls if u.isdigit()), 8)
    with crawl.Fetcher() as f:
        for url in urls:
            try:
                if "/asp/" in url.lower():          # direct Asp URL: teams probe
                    site, base, found = disc.discover(url, span, fetcher=f)
                    entries = [{"tournid": r["tournid"], "kind": "teams",
                                "name": r["series"], "matches": r["matches"]}
                               for r in found]
                else:                               # landing page: classify all
                    site, base, entries = disc.discover_landing(url, f)
            except Exception as e:
                print(f"\n### {url}\n  ERROR: {e}")
                continue
            print(f"\n### {url}\nsite {site}\nbase {base}")
            print(f"  {'tournid':7} {'kind':5} {'matches':7}  name")
            for r in entries:
                m = r.get("matches", "")
                err = f"   [{r['error']}]" if r.get("error") else ""
                print(f"  {r['tournid']:7} {r['kind']:5} {m!s:7}  {r['name']}{err}")
            if a.register:
                for t in disc.plan_registrations(entries, site, base, a.year,
                                                 a.prefix):
                    register(t)
                    print(f"registered '{t.key}': {t.name} ({t.site} "
                          f"{t.tournid}, {t.kind})")


def cmd_reparse(keys: list[str]) -> None:
    keys = _expand(keys) if keys else _cached_keys()
    conn = store.connect()
    for key in keys:
        print(f"=== storing {key} ===", flush=True)
        counts = store.store_tournament(conn, TOURNAMENTS[key])
        print(f"    {counts}", flush=True)
    print("=== deriving ===", flush=True)
    print(f"    {derive_mod.derive(conn)}")
    conn.close()
    cmd_stats([])


def cmd_derive(_keys: list[str]) -> None:
    conn = store.connect()
    print(derive_mod.derive(conn))
    conn.close()


def cmd_stats(_keys: list[str]) -> None:
    conn = store.connect()
    q = conn.execute
    print("\nTournament                         rounds matches  deals  instances  auctions")
    for tid, name in q("SELECT id, name FROM tournament ORDER BY id"):
        rounds = q("SELECT COUNT(*) FROM round WHERE tournament_id=?", (tid,)).fetchone()[0]
        matches = q("SELECT COUNT(*) FROM match m JOIN round r ON r.id=m.round_id "
                    "WHERE r.tournament_id=?", (tid,)).fetchone()[0]
        deals = q("SELECT COUNT(*) FROM deal d JOIN round r ON r.id=d.round_id "
                  "WHERE r.tournament_id=?", (tid,)).fetchone()[0]
        inst = q("SELECT COUNT(*) FROM board_instance bi JOIN match m ON m.id=bi.match_id "
                 "JOIN round r ON r.id=m.round_id WHERE r.tournament_id=?", (tid,)).fetchone()[0]
        auc = q("SELECT COUNT(*) FROM auction a JOIN board_instance bi ON bi.id=a.board_instance_id "
                "JOIN match m ON m.id=bi.match_id JOIN round r ON r.id=m.round_id "
                "WHERE r.tournament_id=?", (tid,)).fetchone()[0]
        print(f"{name[:34]:34} {rounds:6} {matches:7} {deals:6} {inst:10} {auc:9}")
    problems = integrity.check(conn)
    print("\nIntegrity:", "ALL PASS" if not problems else "ISSUES")
    for p in problems:
        print("  -", p)
    conn.close()


COMMANDS = {"ingest": cmd_ingest, "reparse": cmd_reparse,
            "derive": cmd_derive, "stats": cmd_stats, "list": cmd_list,
            "discover": cmd_discover}


def main(argv: list[str]) -> None:
    if not argv or argv[0] not in COMMANDS:
        print(__doc__)
        sys.exit(1 if argv else 0)
    COMMANDS[argv[0]](argv[1:])


if __name__ == "__main__":
    main(sys.argv[1:])
