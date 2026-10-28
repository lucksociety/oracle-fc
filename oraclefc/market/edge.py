"""Post-hoc edge: model probability − market-implied probability.

Joins frozen forecasts with a market snapshot taken AFTER the forecasts were
frozen. Refuses to compare a forecast frozen after the snapshot.
"""
from __future__ import annotations

from .. import frozen
from .jupiter_prices import snapshot


def _edge_row(market, label, model_p, mkt):
    if mkt is None or mkt.get("mid") is None:
        return None
    return {"market": market, "selection": label, "model_p": model_p, "market_mid": mkt["mid"],
            "market_ask": mkt.get("ask"), "edge_vs_mid": model_p - mkt["mid"],
            "edge_vs_ask": (model_p - mkt["ask"]) if mkt.get("ask") else None}


def compute_edges(fc: dict, mk: dict) -> dict:
    s = fc["simulation"]
    rows = []
    ml = mk.get("moneyline", {})
    mids = [ml[k]["mid"] for k in ("home", "draw", "away") if k in ml and ml[k].get("mid")]
    overround = sum(mids) if len(mids) == 3 else None
    for k, lab in (("home", fc["fixture"]["home_name"]), ("draw", "Draw"), ("away", fc["fixture"]["away_name"])):
        r = _edge_row("1X2", lab, s[f"p_{k}"], ml.get(k))
        if r:
            if overround:
                r["market_norm"] = ml[k]["mid"] / overround
                r["edge_vs_norm"] = s[f"p_{k}"] - r["market_norm"]
            rows.append(r)
    if mk.get("btts"):
        r = _edge_row("BTTS", "Yes", s["btts"], mk["btts"])
        if r:
            rows.append(r)
    for line, v in sorted((float(k), v) for k, v in mk.get("totals", {}).items()):
        key = f"over_{line:g}"
        if key in s["totals_over"]:
            rows.append({"market": "Total", "selection": f"Over {line:g}", "model_p": s["totals_over"][key],
                         "market_mid": v["p_over"], "market_ask": None,
                         "edge_vs_mid": s["totals_over"][key] - v["p_over"], "edge_vs_ask": None})
    grid = {f"{t['home']}-{t['away']}": t["p"] for t in s["top_scores"]}
    full = s.get("score_grid")
    for sc, pr in mk.get("exact", {}).items():
        hg, ag = map(int, sc.split("-"))
        p = full[hg][ag] if full and hg < len(full) and ag < len(full) else grid.get(sc)
        if p is not None:
            r = _edge_row("Exact score", sc, float(p), pr)
            if r:
                rows.append(r)
    return {"event_id": fc["fixture"]["event_id"], "overround": overround, "rows": rows}


def edge_for_date(date: str, take_snapshot: bool = True) -> dict:
    fcs = [f for f in frozen.load_date(date) if f.get("status") == "ok" and f["fixture"].get("event_id")]
    fixtures = {f["fixture"]["event_id"]: f["fixture"] for f in fcs}
    snap = snapshot(list(fixtures), date, fixtures) if take_snapshot else None
    out = {"date": date, "label": "POST-HOC COMPARISON — market prices were fetched after the forecasts were "
           "frozen and are never used by the model.", "market_fetched_at": snap["fetched_at"] if snap else None,
           "events": []}
    for fc in fcs:
        eid = fc["fixture"]["event_id"]
        mk = (snap or {}).get("events", {}).get(eid)
        if not mk or "error" in mk:
            continue
        if fc["frozen_at"] > snap["fetched_at"]:
            continue  # forecast frozen after the snapshot: not a valid post-hoc comparison
        e = compute_edges(fc, mk)
        e.update({"home": fc["fixture"]["home_name"], "away": fc["fixture"]["away_name"],
                  "competition": fc["fixture"]["competition"], "kickoff_utc": fc["fixture"]["kickoff_utc"],
                  "frozen_at": fc["frozen_at"], "model_version": fc["model_version"],
                  # prices fetched after kickoff are in-play/settled and not a pre-match comparison
                  "market_after_kickoff": snap["fetched_at"] >= fc["fixture"]["kickoff_utc"]})
        out["events"].append(e)
    return out
