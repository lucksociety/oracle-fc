"""Post-hoc best bet: fees, EV, eligibility, market parsing, JS/Python parity, firewall timing."""
import json
import math
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from oraclefc.market import best_bet as BB
from oraclefc.market import edge as EDGE

ROOT = Path(__file__).resolve().parent.parent


def _pr(by, bs, nb=0, ns=0, vol=10):
    return {"buyYesPriceUsd": int(by * 1e6), "sellYesPriceUsd": int(bs * 1e6),
            "buyNoPriceUsd": int(nb * 1e6), "sellNoPriceUsd": int(ns * 1e6), "volume": vol}


def _ev():
    H, A = "Home FC", "Away FC"
    mk = lambda **k: {"status": "open", "provider": "polymarket",
                       "rulesPrimary": "90 minutes of regular time plus stoppage time", **k}  # noqa: E731
    return H, A, {"markets": [
        mk(marketId="ML-H", sportsMarketType="moneyline", title=H, isTeamMarket=False, pricing=_pr(.50, .49, .51, .50)),
        mk(marketId="ML-D", sportsMarketType="moneyline", title="Draw", isTeamMarket=False, pricing=_pr(.26, .25, .75, .74)),
        mk(marketId="ML-A", sportsMarketType="moneyline", title=A, isTeamMarket=False, pricing=_pr(.26, .25, .75, .74)),
        mk(marketId="BTTS", sportsMarketType="both_teams_to_score", title="Both Teams to Score", pricing=_pr(.55, .54, .46, .45)),
        mk(marketId="T-O", sportsMarketType="totals", title="Over", isTeamMarket=True, sportsLine="2.5", pricing=_pr(.55, .54)),
        mk(marketId="T-U", sportsMarketType="totals", title="Under", isTeamMarket=True, sportsLine="2.5", pricing=_pr(.46, .45)),
        mk(marketId="T-3", sportsMarketType="totals", title="Over", isTeamMarket=True, sportsLine="3", pricing=_pr(.4, .39)),
        mk(marketId="TT", sportsMarketType="soccer_team_totals", title="Under", isTeamMarket=True, sportsLine="1.5",
           team={"name": A}, pricing=_pr(.60, .58)),
        mk(marketId="SP-1", sportsMarketType="spreads", title=A, isTeamMarket=True, sportsLine="-1.5", team={"name": A},
           marketOptions=[{"label": "AWA +1.5", "buyYes": True}], pricing=_pr(.70, .69)),
        mk(marketId="SP-0", sportsMarketType="spreads", title=H, isTeamMarket=True, sportsLine="-1.5", team={"name": H},
           marketOptions=[{"label": "HOM -1.5", "buyYes": True}], pricing=_pr(.31, .30)),
        mk(marketId="EX", sportsMarketType="soccer_exact_score", title=f"{A} 0 - 1 {H}", pricing=_pr(.08, .07, .93, .92)),
        mk(marketId="CLOSED", sportsMarketType="moneyline", title=H, isTeamMarket=False, status="closed", pricing=_pr(.1, .09)),
        mk(marketId="NOASK", sportsMarketType="totals", title="Over", isTeamMarket=True, sportsLine="5.5", pricing=_pr(0, 0)),
        mk(marketId="FULL", sportsMarketType="totals", title="Under", isTeamMarket=True, sportsLine="7.5", pricing=_pr(1.0, .7)),
        mk(marketId="CORN", sportsMarketType="total_corners", title="Over", isTeamMarket=True, sportsLine="9.5", pricing=_pr(.5, .49)),
    ]}


def _grid(lh=1.6, la=1.0, n=11):
    from scipy.stats import poisson
    return np.outer(poisson.pmf(range(n), lh), poisson.pmf(range(n), la)).tolist()


def test_fee_matches_published_schedules():
    # Polymarket sports taker fee table (100 shares): $0.94 at 25c, $1.25 at 50c, $0.45 at 90c
    for p, fee in ((.25, .94), (.5, 1.25), (.9, .45)):
        assert abs(100 * 0.05 * p * (1 - p) - fee) < 0.006
    # + Jupiter builder fee 2% of trade value: 100 @ $0.25 -> $0.50
    assert abs(100 * BB.fee_per_contract(.25) - (0.9375 + 0.50)) < 1e-9


def test_ev_formula_uses_ask_plus_fee():
    cost = 0.5 + 0.02 * 0.5 + 0.05 * 0.25
    assert math.isclose(BB.ev_per_dollar(0.6, 0.5), 0.6 / cost - 1)
    assert BB.ev_per_dollar(0.5, 0.5) < 0  # a fair price is negative EV after fees


def test_selection_parsing():
    H, A, ev = _ev()
    sels = BB.selections_from_event(ev, H, A)
    ids = {(s["market_id"], s["side"]) for s in sels}
    assert ("ML-H", "YES") in ids and ("ML-H", "NO") in ids and ("EX", "NO") in ids
    assert not any(m in {i for i, _ in ids} for m in ("T-3", "CLOSED", "NOASK", "FULL", "CORN"))
    by = {(s["market_id"], s["side"]): s for s in sels}
    assert by[("SP-1", "YES")]["outcome"] == {"kind": "spread", "team": "away", "hcp": 1.5}
    assert by[("SP-0", "YES")]["outcome"] == {"kind": "spread", "team": "home", "hcp": -1.5}
    assert by[("TT", "YES")]["outcome"] == {"kind": "team_total", "team": "away", "line": 1.5, "over": False}
    # exact score listed away-first is mapped to home-away orientation
    assert by[("EX", "YES")]["outcome"] == {"kind": "exact", "h": 1, "a": 0}
    assert by[("ML-H", "NO")]["label"] == "Away FC or draw (NO on Home FC)"


def test_model_probabilities_and_complements():
    g = _grid()
    G = np.asarray(g) / np.sum(g)
    H, A = np.meshgrid(range(11), range(11), indexing="ij")
    assert math.isclose(BB.model_prob({"kind": "spread", "team": "away", "hcp": 1.5}, g), G[(A - H) + 1.5 > 0].sum())
    assert math.isclose(BB.model_prob({"kind": "spread", "team": "home", "hcp": -1.5}, g)
                        + BB.model_prob({"kind": "spread", "team": "away", "hcp": 1.5}, g), 1.0)
    p = BB.model_prob({"kind": "1x2", "res": "H"}, g)
    assert math.isclose(BB.model_prob({"kind": "1x2", "res": "H", "neg": True}, g), 1 - p)
    # headline numbers come from the frozen simulation summary when present
    assert BB.model_prob({"kind": "1x2", "res": "H"}, g, {"p_home": 0.42}) == 0.42
    assert math.isclose(BB.model_prob({"kind": "total", "line": 2.5, "over": False}, g, {"totals_over": {"over_2.5": 0.6}}), 0.4)


def test_eligibility_and_choice():
    H, A, ev = _ev()
    g = _grid()
    res = BB.best_bet(BB.selections_from_event(ev, H, A), g, {"modal_score": {"home": 1, "away": 0}})
    rows = BB.evaluate(BB.selections_from_event(ev, H, A), g, {"modal_score": {"home": 1, "away": 0}})
    for r in rows:
        assert r["eligible"] == (r["score_consistent"] and not r["thin_book"] and r["model_p"] > 0.5 and r["ev_per_dollar"] > 0)
    elig = [r for r in rows if r["eligible"]]
    assert res["verdict"] == "BET" and res["n_eligible"] == len(elig)
    assert math.isclose(res["bet"]["ev_per_dollar"], max(r["ev_per_dollar"] for r in elig), abs_tol=1e-5)
    # a high-EV long shot (P < 50%) is never chosen
    assert all(r["model_p"] > 0.5 for r in [res["bet"], *res["alternatives"]])


def test_no_bet_when_nothing_qualifies():
    H, A, ev = _ev()
    for m in ev["markets"]:  # price every side far above any model probability
        has_no = m["pricing"]["buyNoPriceUsd"]
        m["pricing"] = _pr(.995, .99, .995 if has_no else 0, .99 if has_no else 0)
    res = BB.best_bet(BB.selections_from_event(ev, H, A), _grid(), {"modal_score": {"home": 1, "away": 0}})
    assert res["verdict"] == "NO BET" and "bet" not in res and res["closest"]["ev_per_dollar"] <= 0


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_js_mirror_matches_python():
    H, A, ev = _ev()
    g = _grid(1.3, 1.2, 7)
    sim = {"modal_score": {"home": 1, "away": 0}, "p_home": 0.41, "p_draw": 0.27, "p_away": 0.32, "btts": 0.52, "totals_over": {"over_2.5": 0.49}}
    py = BB.best_bet(BB.selections_from_event(ev, H, A), g, sim)
    js = json.loads(subprocess.check_output(["node", "-e", (
        "const B=require(process.argv[1]);const [ev,g,sim,h,a]=JSON.parse(process.argv[2]);"
        "const r=B.bestBet(B.selectionsFromEvent(ev,h,a),g,sim);"
        "const rows=B.evaluate(B.selectionsFromEvent(ev,h,a),g,sim);"
        "console.log(JSON.stringify({r,rows:rows.map(x=>[x.market_id,x.side,x.label,x.model_p,x.ev_per_dollar,x.eligible])}))"),
        str(ROOT / "web" / "bestbet.js"), json.dumps([ev, g, sim, H, A])]))
    pyrows = [[r["market_id"], r["side"], r["label"], r["model_p"], r["ev_per_dollar"], r["eligible"]]
              for r in BB.evaluate(BB.selections_from_event(ev, H, A), g, sim)]
    assert len(js["rows"]) == len(pyrows)
    for a, b in zip(js["rows"], pyrows):
        assert a[:3] == b[:3] and a[5] == b[5]
        assert math.isclose(a[3], b[3], abs_tol=1e-12) and math.isclose(a[4], b[4], abs_tol=1e-12)
    assert js["r"]["verdict"] == py["verdict"] and js["r"]["bet"]["market_id"] == py["bet"]["market_id"]


def _fc(eid, frozen_at, kickoff):
    return {"status": "ok", "frozen_at": frozen_at, "model_version": "t", "fixture": {
        "event_id": eid, "home_name": "Home FC", "away_name": "Away FC", "competition": "Premier League", "subcategory":"epl", "kickoff_utc": kickoff},
        "simulation": {"modal_score": {"home": 1, "away": 0}, "p_home": .5, "p_draw": .25, "p_away": .25, "btts": .5, "totals_over": {"over_2.5": .5},
                       "top_scores": [], "score_grid": _grid(1.6, 1.0, 7)}}


def test_edge_best_bets_respect_freeze_and_kickoff(monkeypatch):
    H, A, ev = _ev()
    from oraclefc.market.jupiter_prices import parse_event_markets
    mk = parse_event_markets(ev, H, A)
    mk["selections"] = [{**row, "market_id": f"POLY-{i}"}
                        for i, row in enumerate(BB.selections_from_event(ev, H, A))]
    fcs = [_fc("POLY-1", "2026-10-30T10:00:00+00:00", "2026-10-31T15:00:00+00:00"),   # valid pre-match
           _fc("POLY-2", "2026-10-30T13:00:00+00:00", "2026-10-31T15:00:00+00:00"),   # frozen AFTER the snapshot
           _fc("POLY-3", "2026-10-30T10:00:00+00:00", "2026-10-30T11:00:00+00:00"),   # snapshot after kick-off
           _fc("POLY-4", "2026-10-30T10:00:00+00:00", "2026-10-31T15:00:00+00:00")]   # no prices
    snap = {"fetched_at": "2026-10-30T12:00:00+00:00", "events": {"POLY-1": mk, "POLY-2": mk, "POLY-3": mk}}
    monkeypatch.setattr(EDGE.frozen, "load_date", lambda d: fcs)
    monkeypatch.setattr(EDGE, "snapshot", lambda *a, **k: snap)
    monkeypatch.setattr(EDGE, "now_utc_iso", lambda: snap["fetched_at"])
    out = EDGE.edge_for_date("2026-10-30")
    g = {r["event_id"]: r for r in out["best_bets"]["games"]}
    assert g["POLY-1"]["verdict"] == "BET"
    assert g["POLY-2"]["verdict"] == "NO BET" and "after the price snapshot" in g["POLY-2"]["reason"]
    assert g["POLY-3"]["verdict"] == "NO BET" and "kick-off" in g["POLY-3"]["reason"]
    assert g["POLY-4"]["verdict"] == "NO BET" and "no Jupiter prices" in g["POLY-4"]["reason"]
    assert out["best_bets"]["n_bet"] == 1 and out["best_bets"]["n_no_bet"] == 3


def test_report_confidence_describes_current_champion():
    reg = json.loads((ROOT / "experiments" / "registry.json").read_text())
    src = reg["confidence"].get("source") or {}
    assert src.get("model_version") == reg["champion"]["version"], "confidence tables are from an older model"


def test_match_result_must_clear_probability_and_break_even_in_both_components():
    offer = {"outcome": {"kind": "1x2", "res": "A", "neg": True}, "ask": .18,
             "bid": .17, "provider": "polymarket", "label": "Home or draw",
             "market_id": "POLY-1", "market_type": "moneyline", "side": "NO", "volume": 100, "regulation_only": True}
    blend = {"modal_score": {"home": 1, "away": 0}, "p_away": .468749}
    components = {"elo": {"weight": .44, "p_away": .34168},
                  "xg_dc": {"weight": .51, "p_away": .5728}}
    assert BB.best_bet([offer], _grid(), blend)["verdict"] == "BET"
    guarded = BB.best_bet([offer], _grid(), blend, components=components)
    assert guarded["verdict"] == "NO BET"
    assert "main model components" in guarded["reason"]
    components["xg_dc"]["p_away"] = .45
    assert BB.best_bet([offer], _grid(), blend, components=components)["verdict"] == "BET"
    offer["ask"] = .54
    offer["bid"] = .53
    blend["p_away"] = .40
    assert BB.best_bet([offer], _grid(), blend)["verdict"] == "BET"
    assert BB.best_bet([offer], _grid(), blend, components=components)["verdict"] == "NO BET"


@pytest.mark.parametrize("change", [
    {"bid": None}, {"bid": .70}, {"bid": .10}, {"bid": float("nan")},
    {"volume": 0}, {"volume": None}, {"regulation_only": False},
])
def test_unexecutable_quotes_never_qualify(change):
    home, away, event = _ev()
    offer = BB.selections_from_event(event, home, away)[0]
    offer.update(change)
    assert BB.best_bet([offer], _grid(), {"p_home": .8})["verdict"] == "NO BET"


def test_period_and_unverified_regulation_contracts_never_qualify():
    home, away, event = _ev()
    market = event["markets"][0]
    market["periodType"] = "1st"
    assert all(s["market_id"] != market["marketId"] for s in BB.selections_from_event(event, home, away))
    del market["periodType"]
    market["rulesPrimary"] = "Includes extra time and penalties"
    offer = BB.selections_from_event(event, home, away)[0]
    assert BB.best_bet([offer], _grid(), {"p_home": .8})["verdict"] == "NO BET"


def test_individual_quote_time_controls_kickoff_boundary(monkeypatch):
    home, away, event = _ev()
    from oraclefc.market.jupiter_prices import parse_event_markets
    market = parse_event_markets(event, home, away)
    market["selections"] = [{**s, "market_id": "POLY-1"}
                            for s in BB.selections_from_event(event, home, away)]
    market["fetched_at"] = "2026-10-30T12:01:00+00:00"
    forecast = _fc("POLY-1", "2026-10-30T11:00:00+00:00", "2026-10-30T12:00:00+00:00")
    snap = {"fetched_at": "2026-10-30T11:59:00+00:00", "events": {"POLY-1": market}}
    monkeypatch.setattr(EDGE.frozen, "load_date", lambda _: [forecast])
    monkeypatch.setattr(EDGE, "snapshot", lambda *a, **kw: snap)
    monkeypatch.setattr(EDGE, "now_utc_iso", lambda: "2026-10-30T12:01:01+00:00")
    row = EDGE.edge_for_date("2026-10-30")["best_bets"]["games"][0]
    assert row["verdict"] == "NO BET"
    assert row["priced_at"] == market["fetched_at"]


def test_quote_age_validation():
    from datetime import datetime
    now = datetime.fromisoformat("2026-11-05T12:00:00+00:00")
    assert EDGE.fresh_quote("2026-11-05T11:55:00+00:00", now)
    for value in (None, "", "bad", "2026-11-05T12:00:01+00:00", "2026-11-05T11:54:59+00:00"):
        assert not EDGE.fresh_quote(value, now)


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_component_range_and_conservative_ev_match_javascript():
    home, away, event = _ev()
    selections = BB.selections_from_event(event, home, away)
    grid = _grid()
    sim = {"modal_score": {"home": 1, "away": 0}, "p_home": .70, "p_draw": .15, "p_away": .15}
    components = {"elo": {"weight": .44, "p_home": .65, "p_draw": .15, "p_away": .20},
                  "xg": {"weight": .51, "p_home": .72, "p_draw": .13, "p_away": .15}}
    py = BB.best_bet(selections, grid, sim, components=components)
    script = "const B=require(process.argv[1]); console.log(JSON.stringify(B.bestBet(...JSON.parse(process.argv[2]))));"
    js = json.loads(subprocess.check_output(["node", "-e", script, str(ROOT / "web/bestbet.js"),
                                           json.dumps([selections, grid, sim, components])]))
    assert py["bet"]["market_id"] == js["bet"]["market_id"]
    for key in ("component_min_p", "component_max_p", "conservative_ev_per_dollar"):
        assert py["bet"][key] == pytest.approx(js["bet"][key])
