"""`bb` command-line interface (SPEC 7.6).

    bb ingest [keys...]   crawl (network) then parse+store+derive+integrity
    bb reparse            rebuild DB from the raw cache only (no network)
    bb derive             recompute derived tables from the DB
    bb stats              row counts per tournament + integrity check
"""
from __future__ import annotations

import sys

import crawl
import derive as derive_mod
import integrity
import store
from registry import TOURNAMENTS


def _cached_keys() -> list[str]:
    out = []
    for key, t in TOURNAMENTS.items():
        if crawl.cache_path(t, "roundteams_r1.html").exists():
            out.append(key)
    return out


def cmd_ingest(keys: list[str]) -> None:
    keys = keys or list(TOURNAMENTS)
    with crawl.Fetcher() as fetcher:
        for key in keys:
            print(f"=== crawling {key} ===", flush=True)
            crawl.crawl(TOURNAMENTS[key], fetcher)
    cmd_reparse(keys)


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
            "derive": cmd_derive, "stats": cmd_stats}


def main(argv: list[str]) -> None:
    if not argv or argv[0] not in COMMANDS:
        print(__doc__)
        sys.exit(1 if argv else 0)
    COMMANDS[argv[0]](argv[1:])


if __name__ == "__main__":
    main(sys.argv[1:])
