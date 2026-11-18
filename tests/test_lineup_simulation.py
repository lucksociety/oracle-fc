"""Lineup-adjusted simulator grid: produced beside the tested forecast, never instead of it."""
import numpy as np
import pandas as pd

from oraclefc.context import live
from oraclefc.forecast import Engine
from oraclefc.market import grade
from oraclefc.resolve import Resolved
from oraclefc.simulate import score_matrix, summarise


class _Book:
    team_players = {"England:A": ["a1"], "England:B": ["b1"]}
    name = {"a1": "Alpha One", "b1": "Beta One"}
    pos = {"a1": "F", "b1": "F"}


class _LM:
    def __init__(self, book):
        self.book = book

    def configurations(self, team, xi, unavailable, probs, now, rng, k=1):
        # home starts a much stronger XI than usual, away a much weaker one
        return [(0.5, 0.0, 0.0)] if team.endswith(":A") else [(-0.5, 0.0, 0.0)]


class _Eng:
    player_book = _Book()
    as_of = pd.Timestamp("2026-11-21")
    df = pd.DataFrame({"home_key": [], "away_key": [], "date": pd.to_datetime([])})


def _build(monkeypatch, div="E0", kept=None):
    xi = [{"name": f"P{i}", "pos": "M"} for i in range(11)]
    fm = {"source_url": "u", "fetched_at": "t", "lineup_status": "confirmed", "lineup_source": "FotMob",
          "venue": {}, "teams": {s: {"formation": "4-3-3", "starters": xi, "unavailable": []} for s in ("home", "away")}}
    monkeypatch.setattr(live, "find_fotmob_match", lambda *a, **k: {"fm_match_id": 1})
    monkeypatch.setattr(live.fotmob, "match_context", lambda _id: fm)
    monkeypatch.setattr(live.fpl, "availability", lambda: [])
    monkeypatch.setattr(live, "LineupModel", _LM)
    monkeypatch.setattr(live.H, "venues", lambda: pd.DataFrame(columns=["lat", "lon", "venue", "city"]))
    monkeypatch.setattr(live, "weather_forecast", lambda *a, **k: None)
    r = Resolved("A", "B", home="A", away="B", home_key="England:A", away_key="England:B", div=div, country="England")
    base = np.asarray(score_matrix(1.4, 1.1), float)
    base = base[0] if base.ndim == 3 else base
    extras = {}
    shadow = {"lineup": [0.27428, 0.02517, -0.01701, 0.03456]}
    ctx, final = live.build(_Eng(), r, {"kickoff_utc": "2026-11-21T15:00:00+00:00"}, base, kept or {}, shadow, extras=extras)
    return base, ctx, final, extras, r


def test_lineup_grid_is_separate_from_the_tested_forecast(monkeypatch):
    base, ctx, final, extras, r = _build(monkeypatch)
    assert np.allclose(final, base)  # bets are priced from this: unchanged by the unvalidated lineup family
    assert not any(s.get("applied") for s in ctx["factor_shifts"])
    M = extras["lineup_matrix"]
    assert abs(M.sum() - 1) < 1e-9 and not extras["in_main_forecast"]
    sb, sl = summarise(base), summarise(M)
    assert sl["p_home"] > sb["p_home"] and sl["xg_home"] > sb["xg_home"] and sl["xg_away"] < sb["xg_away"]
    # half the fitted size: 0.5 * 0.27428 * 0.5 log units on the home rate
    assert abs(np.log(extras["home_rate_mult"]) - 0.5 * 0.27428 * 0.5) < 1e-3
    eng = Engine.__new__(Engine)
    eng.context_kept, eng.context_unvalidated = {}, []
    ls = eng._lineup_simulation(extras, ctx, sb, r)
    assert ls["applied"] and not ls["validated"] and ls["scale"] == 0.5
    assert ls["basis"] == {"home": "confirmed", "away": "confirmed"}
    assert 0.99 < np.sum(ls["score_grid"]) <= 1 + 1e-9 and ls["p_home"] == sl["p_home"]


def test_no_player_ratings_means_lineup_shown_but_not_applied(monkeypatch):
    base, ctx, final, extras, r = _build(monkeypatch, div="BRA")
    assert "lineup_matrix" not in extras and np.allclose(final, base)
    assert ctx["lineups"]["home"]["formation"] == "4-3-3" and len(ctx["lineups"]["home"]["starters"]) == 11
    eng = Engine.__new__(Engine)
    eng.context_kept, eng.context_unvalidated = {}, []
    ls = eng._lineup_simulation(extras, ctx, summarise(base), r)
    assert ls["applied"] is False and "No player ratings" in ls["reason"]


def test_grading_compares_tested_and_lineup_forecasts():
    games = [{"status": "final", "metrics": {**grade.forecast_metrics({"p_home": .5, "p_draw": .25, "p_away": .25, "xg_total": 2.5}, 2, 0),
                                             "lineup_log_loss": 0.5, "lineup_rps": 0.1}},
             {"status": "final", "metrics": grade.forecast_metrics({"p_home": .5, "p_draw": .25, "p_away": .25, "xg_total": 2.5}, 0, 0)}]
    v = grade.summarise(games)["vs_lineup"]
    assert v["n"] == 1 and abs(v["log_loss_diff"] - (0.5 + np.log(0.5))) < 1e-9
    assert grade.summarise(games[1:])["vs_lineup"] is None
