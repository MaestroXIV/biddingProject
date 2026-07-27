"""Assemble a single self-contained BoardBase HTML (SQLite-in-the-browser).

Inlines: the web app CSS, the sql.js engine, the WASM binary (base64), and the
gzipped database (base64). Output opens from file:// with no server, no network.
"""
from __future__ import annotations

import base64
import gzip
import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHARE = ROOT / "share"
OUT = ROOT / "dist" / "BoardBase.html"


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def main() -> None:
    # 1) compact copy of the DB
    min_db = SHARE / "boardbase_min.db"
    if min_db.exists():
        min_db.unlink()
    con = sqlite3.connect(ROOT / "data" / "boardbase.db")
    con.execute(f"VACUUM INTO '{min_db}'")
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

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html)
    min_db.unlink()
    print(f"wrote {OUT.relative_to(ROOT)}  ({OUT.stat().st_size/1e6:.1f} MB)")


if __name__ == "__main__":
    main()
