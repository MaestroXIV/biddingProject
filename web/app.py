"""BoardBase browse UI (SPEC 7.1/7.2). Run: uvicorn web.app:app --reload

Local-first study tool: search board instances, open a deal traveller, follow
provenance links back to the official EBL/WBF pages.
"""
from __future__ import annotations

import csv
import io
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import queries as q
import render as rnd

BASE = Path(__file__).resolve().parent
app = FastAPI(title="BoardBase")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")
templates.env.filters["hand"] = rnd.hand_html
templates.env.filters["call"] = rnd.call_html
templates.env.globals["auction_grid"] = rnd.auction_grid
templates.env.globals["auction_oneliner"] = rnd.auction_oneliner
templates.env.globals["SEATS_WNES"] = rnd.SEATS_WNES

_CARRY = ("tournament", "player", "player_role", "partner", "pair_side",
          "dealer", "vul", "round_from", "round_to")


def _url(path: str, f: dict, seq: str | None = None, **extra) -> str:
    d = {k: f[k] for k in _CARRY if f.get(k)}
    if seq:
        d["seq"] = seq
    d.update({k: v for k, v in extra.items() if v})
    return f"{path}?{urlencode(d)}" if d else path


templates.env.globals["explore_url"] = lambda f, seq=None, **e: _url("/explore", f, seq, **e)
templates.env.globals["search_url"] = lambda f, seq=None, **e: _url("/", f, seq, **e)

PAGE = 40


def _filters(params) -> dict:
    keys = ("tournament", "player", "player_role", "partner", "pair_side",
            "opening_call", "position", "dealer", "vul", "competitive",
            "contract", "declarer", "round_from", "round_to", "seq")
    return {k: (params.get(k) or "").strip() for k in keys}


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    params = request.query_params
    f = _filters(params)
    page = max(0, int(params.get("page", 0) or 0))
    conn = q.connect()
    has_query = any(f.values())
    total, results = (0, [])
    if has_query:
        total, results = q.search(conn, f, limit=PAGE, offset=page * PAGE)
    ctx = {
        "request": request, "f": f, "results": results, "total": total,
        "page": page, "page_size": PAGE, "has_query": has_query,
        "tournaments": q.tournaments(conn), "opening_calls": q.opening_calls(conn),
        "qs": params,
    }
    conn.close()
    return templates.TemplateResponse(request, "index.html", ctx)


@app.get("/explore", response_class=HTMLResponse)
def explore(request: Request):
    params = request.query_params
    f = _filters(params)
    seq = f.get("seq", "")
    nh_min = (params.get("next_hcp_min") or "").strip()
    nh_max = (params.get("next_hcp_max") or "").strip()
    conn = q.connect()
    result = q.explore(conn, f, seq, nh_min, nh_max)
    ctx = {
        "request": request, "f": f, "result": result,
        "next_hcp_min": nh_min, "next_hcp_max": nh_max,
        "tournaments": q.tournaments(conn), "opening_calls": q.opening_calls(conn),
        "qs": params,
    }
    conn.close()
    return templates.TemplateResponse(request, "explore.html", ctx)


@app.get("/player", response_class=HTMLResponse)
def player(request: Request):
    name = (request.query_params.get("name") or "").strip()
    tournament = (request.query_params.get("tournament") or "").strip()
    conn = q.connect()
    hit = q.resolve_one_player(conn, name)
    if not hit:
        ctx = {"request": request, "name": name, "player": None,
               "tournaments": q.tournaments(conn)}
        conn.close()
        return templates.TemplateResponse(request, "player.html", ctx)
    pid, canonical = hit
    grid = q.opening_grid(conn, [pid], tournament=tournament)
    base = {"player": canonical}
    if tournament:
        base["tournament"] = tournament

    def explore_for(call):
        return "/explore?" + urlencode({**base, "seq": call})
    ctx = {
        "request": request, "player": {"id": pid, "name": canonical},
        "grid": grid, "names": {pid: canonical}, "tournament": tournament,
        "events": q.player_events(conn, pid),
        "partners": q.player_partners(conn, pid, tournament),
        "explore_for": explore_for,
        "boards_all": "/?" + urlencode(base),
        "boards_opener": "/?" + urlencode({**base, "player_role": "opener"}),
        "tournaments": q.tournaments(conn), "POS": q._POS, "VULS": q._VULS,
    }
    conn.close()
    return templates.TemplateResponse(request, "player.html", ctx)


@app.get("/pair", response_class=HTMLResponse)
def pair(request: Request):
    p = request.query_params
    n1 = (p.get("p1") or "").strip()
    n2 = (p.get("p2") or "").strip()
    tournament = (p.get("tournament") or "").strip()
    conn = q.connect()
    h1 = q.resolve_one_player(conn, n1)
    h2 = q.resolve_one_player(conn, n2)
    if not (h1 and h2):
        ctx = {"request": request, "p1": n1, "p2": n2, "pair": None,
               "tournaments": q.tournaments(conn)}
        conn.close()
        return templates.TemplateResponse(request, "pair.html", ctx)
    (id1, name1), (id2, name2) = h1, h2
    key = q.pair_key_for(id1, id2)
    grid = q.opening_grid(conn, [id1, id2], pair_key=key, tournament=tournament)
    base = {"player": n1, "partner": n2, "pair_side": "opening"}
    if tournament:
        base["tournament"] = tournament

    def explore_for(call):
        return "/explore?" + urlencode({**base, "seq": call})
    pair_search = "/?" + urlencode(base)
    ctx = {
        "request": request,
        "pair": {"id1": id1, "id2": id2, "name1": name1, "name2": name2,
                 "n1_in": n1, "n2_in": n2},
        "grid": grid, "names": {id1: name1, id2: name2},
        "member_ids": [id1, id2], "tournament": tournament,
        "events": q.player_events(conn, id1),
        "explore_for": explore_for, "pair_search": pair_search,
        "tournaments": q.tournaments(conn), "POS": q._POS, "VULS": q._VULS,
    }
    conn.close()
    return templates.TemplateResponse(request, "pair.html", ctx)


@app.get("/deal/{deal_id}", response_class=HTMLResponse)
def deal(request: Request, deal_id: int, opening_call: str = ""):
    conn = q.connect()
    header = q.deal_header(conn, deal_id)
    if header is None:
        conn.close()
        return HTMLResponse("Deal not found", status_code=404)
    insts = q.deal_instances(conn, deal_id, opening_call)
    rows = []
    for r in insts:
        players = q.players_at(conn, r["match_id"], r["room"])
        rows.append({
            "r": r,
            "players": players,
            "calls_list": r["calls"].split() if r["calls"] else [],
        })
    ctx = {
        "request": request, "d": header, "rows": rows,
        "opening_calls": q.deal_opening_calls(conn, deal_id),
        "opening_call": opening_call,
        "board_across": header["source_url"],
        "board_details_base": header["asp_base_url"],
    }
    conn.close()
    return templates.TemplateResponse(request, "deal.html", ctx)


@app.get("/export.csv")
def export_csv(request: Request):
    f = _filters(request.query_params)
    conn = q.connect()
    _, results = q.search(conn, f, limit=100_000, offset=0)
    conn.close()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["tournament", "round", "board", "room", "home_team",
                "visiting_team", "dealer", "vul", "opening_call", "opener_seat",
                "contract", "declarer", "tricks", "score_ns", "score_ew",
                "auction", "source_url"])
    for r in results:
        w.writerow([r["tslug"], r["round_no"], r["board_no"], r["room"],
                    r["home_team"], r["visiting_team"], r["dealer"], r["vul"],
                    r["opening_call"] or "", r["opener_seat"] or "",
                    r["contract"], r["declarer"], r["tricks"],
                    r["score_ns"], r["score_ew"],
                    " ".join(r["calls_list"]), r["source_url"]])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=boardbase.csv"})
