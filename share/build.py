"""Assemble a single self-contained BoardBase HTML (SQLite-in-the-browser).

Inlines: the web app CSS, the sql.js engine, the WASM binary (base64), and the
gzipped database (base64). Output opens from file:// with no server, no network.
"""
from __future__ import annotations

import argparse
import base64
import gzip
import sqlite3
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHARE = ROOT / "share"
OUT = ROOT / "dist" / "BoardBase.html"


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "boardbase.db",
                    help="source SQLite DB (default: data/boardbase.db)")
    ap.add_argument("--out", type=Path, default=OUT,
                    help="output HTML (default: dist/BoardBase.html)")
    args = ap.parse_args(argv)
    out = args.out.resolve()

    # 1) compact copy of the DB (source opened read-only, never modified)
    tmpdir = tempfile.TemporaryDirectory()
    min_db = Path(tmpdir.name) / "boardbase_min.db"
    con = sqlite3.connect(f"file:{args.db.resolve()}?mode=ro", uri=True)
    con.execute("VACUUM INTO ?", (str(min_db),))
    con.close()

    css = (ROOT / "web" / "static" / "style.css").read_text()
    sqljs = (SHARE / "vendor" / "sql-wasm.js").read_text()
    wasm_b64 = b64((SHARE / "vendor" / "sql-wasm.wasm").read_bytes())
    db_gz_b64 = b64(gzip.compress(min_db.read_bytes(), 9))

    html = (SHARE / "app.html").read_text()
    html = html.replace("/*__CSS__*/", css)
    html = html.replace("/*__SQLJS__*/", sqljs)
    html = html.replace("/*__WASM_B64__*/", wasm_b64)
    html = html.replace("/*__DB_GZ_B64__*/", db_gz_b64)

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html)
    tmpdir.cleanup()
    print(f"wrote {out}  ({out.stat().st_size/1e6:.1f} MB)")


if __name__ == "__main__":
    main()
