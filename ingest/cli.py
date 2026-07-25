"""`bb` command-line interface (SPEC 7.6).

    bb ingest [keys...]   crawl (network) then parse+store+derive+integrity
    bb ingest --site EBL --base <AspURL> --tournid N --name "..." --year Y
              [--series "..."] [--key slug]    register + ingest a NEW event
    bb reparse            rebuild DB from the raw cache only (no network)
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
from registry import TOURNAMENTS, Tournament, register


def _register_from_flags(argv: list[str]) -> str:
    p = argparse.ArgumentParser(prog="bb ingest", add_help=False)
    p.add_argument("--site", required=True, choices=["EBL", "WBF"])
    p.add_argument("--base", required=True)
    p.add_argument("--tournid", required=True, type=int)
    p.add_argument("--name", required=True)
    p.add_argument("--year", required=True, type=int)
    p.add_argument("--series", default="")
    p.add_argument("--key", default=None)
    a = p.parse_args(argv)
    base = a.base if a.base.endswith("/") else a.base + "/"
    key = a.key or re.sub(r"[^a-z0-9]+", "-",
                          f"{a.name}-{a.year}".lower()).strip("-")
    t = Tournament(key=key, site=a.site, base=base, tournid=a.tournid,
                   name=a.name, year=a.year, series=a.series)
    register(t)
    print(f"registered '{key}': {a.name} ({a.site} {a.tournid})")
    return key


def _cached_keys() -> list[str]:
    out = []
    for key, t in TOURNAMENTS.items():
        if crawl.cache_path(t, "roundteams_r1.html").exists():
            out.append(key)
    return out


def cmd_ingest(keys: list[str]) -> None:
    if any(a.startswith("--") for a in keys):     # new event by flags
        keys = [_register_from_flags(keys)]
    keys = keys or list(TOURNAMENTS)
    with crawl.Fetcher() as fetcher:
        for key in keys:
            print(f"=== crawling {key} ===", flush=True)
            crawl.crawl(TOURNAMENTS[key], fetcher)
    cmd_reparse(keys)


def cmd_list(_keys: list[str]) -> None:
    for key, t in TOURNAMENTS.items():
        print(f"  {key:16} {t.site} {t.tournid}  {t.name} ({t.year})")


def cmd_discover(args: list[str]) -> None:
    import discover as disc
    url = args[0]
    span = int(args[1]) if len(args) > 1 else 12
    site, base, found = disc.discover(url, span)
    print(f"site {site}\nbase {base}\n")
    print(f"  {'tournid':7} {'matches':7}  series")
    for r in found:
        print(f"  {r['tournid']:7} {r['matches']:7}  {r['series']}")
    print("\nTeam RR events usually show 12-16 matches. To ingest, e.g.:")
    if found:
        r = found[0]
        print(f"  bb ingest --site {site} --base {base} --tournid {r['tournid']} "
              f"--name \"{r['series']} <year>\" --year <year>")


def cmd_reparse(keys: list[str]) -> None:
    keys = keys or _cached_keys()
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
