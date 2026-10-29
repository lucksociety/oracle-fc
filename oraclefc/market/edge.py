"""Post-hoc edge: model probability − market-implied probability.

Joins frozen forecasts with a market snapshot taken AFTER the forecasts were
frozen. Refuses to compare a forecast frozen after the snapshot.
"""
from __future__ import annotations

import json

from .. import config, frozen
from .best_bet import FEES, MIN_P, best_bet
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
           "events": [], "best_bets": best_bets_meta()}
    rows = []
    for fc in fcs:
        eid = fc["fixture"]["event_id"]
        mk = (snap or {}).get("events", {}).get(eid)
        bb_row = {"event_id": eid, "home": fc["fixture"]["home_name"], "away": fc["fixture"]["away_name"],
                  "competition": fc["fixture"]["competition"], "kickoff_utc": fc["fixture"]["kickoff_utc"],
                  "frozen_at": fc["frozen_at"], "model_version": fc["model_version"]}
        rows.append(bb_row)
        if not mk or "error" in mk:
            bb_row.update(verdict="NO BET", reason="no Jupiter prices captured for this game")
            continue
        if fc["frozen_at"] > snap["fetched_at"]:
            bb_row.update(verdict="NO BET", reason="forecast frozen after the price snapshot")
            continue  # forecast frozen after the snapshot: not a valid post-hoc comparison
        after = snap["fetched_at"] >= fc["fixture"]["kickoff_utc"]
        e = compute_edges(fc, mk)
        e.update({"home": fc["fixture"]["home_name"], "away": fc["fixture"]["away_name"],
                  "competition": fc["fixture"]["competition"], "kickoff_utc": fc["fixture"]["kickoff_utc"],
                  "frozen_at": fc["frozen_at"], "model_version": fc["model_version"],
                  # prices fetched after kickoff are in-play/settled and not a pre-match comparison
                  "market_after_kickoff": after})
        if after:
            bb_row.update(verdict="NO BET", reason="prices were fetched after kick-off (in-play), not pre-match")
        elif "selections" not in mk:
            bb_row.update(verdict="NO BET", reason="snapshot has no buyable-side data")
        else:
            bb_row.update(best_bet(mk["selections"], fc["simulation"]["score_grid"], fc["simulation"]))
        e["best_bet"] = {k: v for k, v in bb_row.items() if k not in ("home", "away", "competition", "kickoff_utc")}
        out["events"].append(e)
    for r in rows:
        r["priced_at"] = out["market_fetched_at"]
    rows = lock_pre_kickoff(rows, _previous_games(date))
    rows.sort(key=lambda r: r.get("kickoff_utc") or "")
    out["best_bets"]["games"] = rows
    out["best_bets"]["n_games"] = len(rows)
    out["best_bets"]["n_bet"] = sum(r.get("verdict") == "BET" for r in rows)
    out["best_bets"]["n_no_bet"] = len(rows) - out["best_bets"]["n_bet"]
    return out


def _previous_games(date: str) -> dict:
    p = config.DATA_DIR / "edge" / f"{date}.json"
    if not p.exists():
        return {}
    try:
        prev = json.loads(p.read_text())
    except ValueError:
        return {}
    fetched = prev.get("market_fetched_at")
    return {g["event_id"]: {**g, "priced_at": g.get("priced_at") or fetched}
            for g in (prev.get("best_bets") or {}).get("games", []) if g.get("event_id")}


def _pre_kickoff(g: dict) -> bool:
    return bool(g.get("priced_at") and g.get("kickoff_utc") and g["priced_at"] < g["kickoff_utc"]
                and "after kick-off" not in (g.get("reason") or ""))


def lock_pre_kickoff(rows: list[dict], prev: dict) -> list[dict]:
    """Once a game kicks off its best bet is LOCKED at the last pre-kick-off verdict: later (in-play
    or settled) snapshots never overwrite it, so bets can be graded against what was published."""
    out = []
    for r in rows:
        p = prev.get(r["event_id"])
        started_now = not _pre_kickoff(r)
        if started_now and p and _pre_kickoff(p):
            r = {**p, "locked": True, "locked_from_snapshot": p["priced_at"]}
        out.append(r)
    return out


def best_bets_meta() -> dict:
    return {"rule": f"Per game, the single selection with the highest EV among those with model P > {MIN_P:.0%} "
                    "and EV > 0 when buying at the Jupiter ask (YES or NO) including trading fees; otherwise NO BET.",
            "ev_formula": "EV per $1 = p_model / (ask + fee per contract) - 1",
            "fees": FEES,
            "markets": "full-time goals markets priced from the frozen score grid: 1X2 (YES/NO), BTTS, totals, "
                       "team totals, spreads, exact score. Half-time, corners and first-to-score are not modelled."}
