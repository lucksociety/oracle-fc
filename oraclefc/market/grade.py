"""POST-MATCH grading of frozen forecasts and published best bets (never feeds the model).

For a date, every frozen forecast and its pre-kick-off best bet is joined with the final
90-minute score from FotMob (``ingest.fotmob.day_results``), then:

* forecast metrics: 1X2 RPS and log loss, exact-score hit (modal score), top-5 hit, actual
  score probability, total-goals error;
* best bets: settled WIN / LOSS at 1 unit staked buying at the recorded ask + fees
  (profit on a win = 1 / cost - 1, a loss = -1).

A game whose result cannot be found is marked ``unknown``; nothing is ever guessed.
Output: ``data/results/<date>.json`` plus a running record in ``data/results/record.json``.
"""
from __future__ import annotations

import json
import math
import re
from datetime import datetime, timedelta, timezone

import numpy as np

from .. import config, frozen
from ..teams import match_team

RESULTS_DIR = config.DATA_DIR / "results"
EDGE_DIR = config.DATA_DIR / "edge"
HCP_RE = re.compile(r"^(?P<team>.+?)\s+(?P<hcp>[+-]\d+(?:\.\d+)?)$")


# ------------------------------------------------------------------ settlement
def parse_label(label: str, home: str, away: str) -> dict | None:
    """Outcome spec for bets recorded before the spec was stored alongside the bet."""
    s = (label or "").strip()
    if s.startswith("NO — "):
        inner = parse_label(s[5:], home, away)
        return {**inner, "neg": not inner.get("neg")} if inner else None
    if s == "Both teams to score — NO":
        return {"kind": "btts", "neg": True}
    if s == "Both teams to score":
        return {"kind": "btts"}
    if s == "Draw":
        return {"kind": "1x2", "res": "D"}
    if s == "Either team to win (NO on draw)":
        return {"kind": "1x2", "res": "D", "neg": True}
    if s == f"{away} or draw (NO on {home})":
        return {"kind": "1x2", "res": "H", "neg": True}
    if s == f"{home} or draw (NO on {away})":
        return {"kind": "1x2", "res": "A", "neg": True}
    if s == f"{home} to win":
        return {"kind": "1x2", "res": "H"}
    if s == f"{away} to win":
        return {"kind": "1x2", "res": "A"}
    m = re.match(r"^Exact score (\d+)-(\d+)$", s)
    if m:
        return {"kind": "exact", "h": int(m.group(1)), "a": int(m.group(2))}
    m = re.match(r"^Any score except (\d+)-(\d+)$", s)
    if m:
        return {"kind": "exact", "h": int(m.group(1)), "a": int(m.group(2)), "neg": True}
    m = re.match(r"^(Over|Under) (\d+(?:\.\d+)?) goals$", s)
    if m:
        return {"kind": "total", "line": float(m.group(2)), "over": m.group(1) == "Over"}
    for team, side in ((home, "home"), (away, "away")):
        m = re.match(rf"^{re.escape(team)} (over|under) (\d+(?:\.\d+)?) goals$", s)
        if m:
            return {"kind": "team_total", "team": side, "line": float(m.group(2)), "over": m.group(1) == "over"}
        m = HCP_RE.match(s)
        if m and m.group("team") == team:
            return {"kind": "spread", "team": side, "hcp": float(m.group("hcp"))}
    return None


def settle(spec: dict, hg: int, ag: int) -> bool:
    k = spec["kind"]
    if k == "1x2":
        hit = {"H": hg > ag, "D": hg == ag, "A": hg < ag}[spec["res"]]
    elif k == "btts":
        hit = hg > 0 and ag > 0
    elif k == "total":
        hit = (hg + ag) > spec["line"] if spec["over"] else (hg + ag) < spec["line"]
    elif k == "team_total":
        g = hg if spec["team"] == "home" else ag
        hit = g > spec["line"] if spec["over"] else g < spec["line"]
    elif k == "spread":
        diff = (hg - ag) if spec["team"] == "home" else (ag - hg)
        hit = diff + spec["hcp"] > 0
    elif k == "exact":
        hit = hg == spec["h"] and ag == spec["a"]
    else:
        raise ValueError(k)
    return (not hit) if spec.get("neg") else hit


def bet_pnl(bet: dict, won: bool, stake: float = 1.0) -> float:
    cost = bet.get("cost_per_contract") or (bet["ask"] + (bet.get("fee_per_contract") or 0.0))
    return stake * (1.0 / cost - 1.0) if won else -stake


# ------------------------------------------------------------------ results lookup
def _utc_days(date: str) -> list[str]:
    d = datetime.fromisoformat(date).date()
    return [(d + timedelta(days=i)).isoformat() for i in (-1, 0, 1)]


def find_result(fx: dict, results: list[dict]) -> dict | None:
    """Match a fixture to a FotMob result: same kick-off (±3h) and both team names resolve."""
    ko = datetime.fromisoformat(fx["kickoff_utc"])
    cands = []
    for r in results:
        if not r.get("utc"):
            continue
        t = datetime.fromisoformat(r["utc"].replace("Z", "+00:00"))
        if abs((t - ko).total_seconds()) <= 3 * 3600:
            cands.append(r)
    if not cands:
        return None
    homes = [r["home"] for r in cands]
    for name in (fx.get("home_name"), fx.get("home_matched")):
        if not name:
            continue
        m = match_team(name, homes, threshold=0.75)
        if m.canonical:
            hits = [r for r in cands if r["home"] == m.canonical]
            for r in hits:
                for an in (fx.get("away_name"), fx.get("away_matched")):
                    if an and match_team(an, [r["away"]], threshold=0.6).canonical:
                        return r
    return None


def _results_for(date: str, fetch=None) -> list[dict]:
    if fetch is None:
        from ..ingest.fotmob import day_results as fetch
    out = []
    for d in _utc_days(date):
        try:
            out.extend(fetch(d))
        except Exception as e:  # noqa: BLE001 — a missing day just leaves games unknown
            print(f"   ! results fetch {d} failed: {e}")
    return out


# ------------------------------------------------------------------ forecast metrics
def forecast_metrics(sim: dict, hg: int, ag: int) -> dict:
    p = np.array([sim["p_home"], sim["p_draw"], sim["p_away"]], float)
    o = 0 if hg > ag else (1 if hg == ag else 2)
    oh = np.eye(3)[o]
    rps = float(((np.cumsum(p)[:2] - np.cumsum(oh)[:2]) ** 2).sum() / 2)
    ll = float(-math.log(max(p[o], 1e-12)))
    grid = sim.get("score_grid")
    p_exact = None
    if grid and hg < len(grid) and ag < len(grid[0]):
        g = np.asarray(grid, float)
        p_exact = float(g[hg, ag] / g.sum())
    top = [(t["home"], t["away"]) for t in sim.get("top_scores", [])[:5]]
    ms = sim.get("modal_score") or {}
    return {"rps": rps, "log_loss": ll, "p_actual_outcome": float(p[o]),
            "exact_hit": (ms.get("home"), ms.get("away")) == (hg, ag), "top5_hit": (hg, ag) in top,
            "p_actual_score": p_exact, "pred_total": sim.get("xg_total"), "total_goals": hg + ag,
            "outcome": "HDA"[o], "predicted": "HDA"[int(p.argmax())]}


def _pre_kickoff_forecast(date: str, event_id: str, kickoff: str) -> dict | None:
    d = config.FORECAST_DIR / date / frozen._safe(event_id)
    best = None
    for p in d.glob("*.json") if d.exists() else []:
        rec = json.loads(p.read_text())
        if rec.get("status") != "ok" or rec.get("frozen_at", "") > kickoff:
            continue
        if best is None or rec["frozen_at"] > best["frozen_at"]:
            best = rec
    return best


# ------------------------------------------------------------------ grading
def grade_date(date: str, fetch=None, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    edge_p = EDGE_DIR / f"{date}.json"
    edge = json.loads(edge_p.read_text()) if edge_p.exists() else {}
    bets = {g["event_id"]: g for g in (edge.get("best_bets") or {}).get("games", [])}
    events = {}
    for rec in frozen.load_date(date):
        if rec.get("status") == "ok" and rec["fixture"].get("event_id"):
            events[rec["fixture"]["event_id"]] = rec["fixture"]
    results = _results_for(date, fetch)
    games = []
    for eid, fx in sorted(events.items(), key=lambda kv: kv[1].get("kickoff_utc") or ""):
        fc = _pre_kickoff_forecast(date, eid, fx["kickoff_utc"])
        bb = bets.get(eid) or {"verdict": "NO BET", "reason": "no best-bet record"}
        row = {"event_id": eid, "home": fx["home_name"], "away": fx["away_name"],
               "competition": fx.get("competition"), "kickoff_utc": fx["kickoff_utc"],
               "forecast_frozen_at": fc["frozen_at"] if fc else None,
               "model_version": fc["model_version"] if fc else None, "verdict": bb.get("verdict")}
        if fc:
            s = fc["simulation"]
            row["prediction"] = {"modal_score": f"{s['modal_score']['home']}-{s['modal_score']['away']}",
                                 "p_home": s["p_home"], "p_draw": s["p_draw"], "p_away": s["p_away"],
                                 "xg_home": s["xg_home"], "xg_away": s["xg_away"]}
        if bb.get("verdict") == "BET":
            row["bet"] = {k: bb["bet"].get(k) for k in ("label", "market_type", "side", "ask", "fee_per_contract",
                                                         "cost_per_contract", "model_p", "ev_per_dollar", "volume")}
            row["bet_locked_at"] = bb.get("locked_from_snapshot") or edge.get("market_fetched_at")
        else:
            row["no_bet_reason"] = bb.get("reason")
        r = find_result(fx, results)
        if r is None or not r.get("finished") or r.get("score_ft") is None:
            started = datetime.fromisoformat(fx["kickoff_utc"]) < now
            row["status"] = "unknown" if started else "pending"
            row["result_note"] = ("result not found / not final at source" if started else "not played yet")
            if r is not None:
                row["source"] = {"fotmob_match_id": r["fm_match_id"], "status": r.get("status")}
            games.append(row)
            continue
        hg, ag = r["score_ft"]
        row["status"] = "final"
        row["result"] = {"score_90": f"{hg}-{ag}", "note": r.get("score_note"),
                         "source": f"FotMob match {r['fm_match_id']}",
                         "url": f"https://www.fotmob.com/match/{r['fm_match_id']}"}
        if fc:
            row["metrics"] = forecast_metrics(fc["simulation"], hg, ag)
        if row.get("bet"):
            spec = bb["bet"].get("outcome") or parse_label(bb["bet"]["label"], fx["home_name"], fx["away_name"])
            if spec is None:
                row["bet_result"] = "unknown"
            else:
                won = settle(spec, hg, ag)
                row["bet_result"] = "WIN" if won else "LOSS"
                row["pnl_units"] = round(bet_pnl(bb["bet"], won), 4)
        games.append(row)
    return {"date": date, "graded_at": now.isoformat(timespec="seconds"),
            "label": "POST-MATCH grading. Results never feed the model's market-free inputs except as the "
                     "ordinary historical results every model is fitted on.",
            "stake": "1 unit per bet, bought at the recorded Jupiter ask + fees",
            "games": games, "summary": summarise(games)}


def summarise(games: list[dict]) -> dict:
    fin = [g for g in games if g.get("metrics")]
    bets = [g for g in games if g.get("bet_result") in ("WIN", "LOSS")]
    w = sum(g["bet_result"] == "WIN" for g in bets)
    pnl = sum(g["pnl_units"] for g in bets)
    staked = len(bets)
    return {
        "n_games": len(games), "n_final": len(fin),
        "n_unknown": sum(g["status"] == "unknown" for g in games),
        "n_pending": sum(g["status"] == "pending" for g in games),
        "bets": {"n": staked, "wins": w, "losses": staked - w, "units": round(pnl, 4),
                 "roi": round(pnl / staked, 4) if staked else None,
                 "expected_units": round(sum(g["bet"]["ev_per_dollar"] for g in bets), 4),
                 "pending_or_unknown": sum(1 for g in games if g.get("bet") and g.get("bet_result") not in ("WIN", "LOSS"))},
        "forecast": None if not fin else {
            "rps": float(np.mean([g["metrics"]["rps"] for g in fin])),
            "log_loss": float(np.mean([g["metrics"]["log_loss"] for g in fin])),
            "exact_hits": int(sum(g["metrics"]["exact_hit"] for g in fin)),
            "top5_hits": int(sum(g["metrics"]["top5_hit"] for g in fin)),
            "result_hits": int(sum(g["metrics"]["outcome"] == g["metrics"]["predicted"] for g in fin)),
            "mean_pred_total": float(np.mean([g["metrics"]["pred_total"] for g in fin])),
            "mean_actual_total": float(np.mean([g["metrics"]["total_goals"] for g in fin])),
        },
    }


def running_record() -> dict:
    days, all_games = [], []
    for p in sorted(RESULTS_DIR.glob("20*.json")):
        d = json.loads(p.read_text())
        days.append({"date": d["date"], **{k: d["summary"][k] for k in ("n_final", "bets")},
                     "rps": (d["summary"].get("forecast") or {}).get("rps")})
        all_games.extend(d["games"])
    s = summarise(all_games)
    cum, curve = 0.0, []
    for g in sorted((g for g in all_games if g.get("bet_result") in ("WIN", "LOSS")), key=lambda g: g["kickoff_utc"]):
        cum += g["pnl_units"]
        curve.append({"kickoff_utc": g["kickoff_utc"], "units": round(cum, 4)})
    return {"updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "overall": s,
            "by_day": days, "units_curve": curve,
            "caveat": "Small sample. There is no historical betting backtest (Directive Zero forbids historical "
                      "odds), so this live record is the only evidence of betting performance."}


def write(date: str, res: dict) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / f"{date}.json").write_text(json.dumps(res, indent=1, default=str))
    (RESULTS_DIR / "record.json").write_text(json.dumps(running_record(), indent=1, default=str))
