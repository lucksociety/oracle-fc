"""Match-context layer: tilt maths, feature transforms, allow-list parsers, staging."""
import math

import numpy as np
import pytest
from scipy.stats import poisson

from oraclefc import config, frozen
from oraclefc.context import spec
from oraclefc.context.live import _shift, name_match
from oraclefc.context.tilt import fit_coefficients, tilt
from oraclefc.governance import MarketContamination, assert_no_market_keys
from oraclefc.ingest import fotmob


def _pois(lh, la, G=11):
    k = np.arange(G)
    return np.outer(poisson.pmf(k, lh), poisson.pmf(k, la))


def test_tilt_is_poisson_rate_multiplier():
    P = _pois(1.4, 1.1, 25)
    Q = tilt(P, math.log(1.2), math.log(0.9))
    assert abs(Q.sum() - 1) < 1e-12
    R = _pois(1.4 * 1.2, 1.1 * 0.9, 25)
    assert np.abs(Q / Q.sum() - R / R.sum()).max() < 1e-9


def test_tilt_zero_is_identity_and_batched():
    P = np.stack([_pois(1.2, 1.0), _pois(2.0, 0.7)])
    assert np.allclose(tilt(P, [0, 0], [0, 0]), P / P.sum((1, 2), keepdims=True))


def test_fit_recovers_sign():
    rng = np.random.default_rng(0)
    n = 4000
    x = rng.random(n)
    lh = 1.4 * np.exp(0.3 * x)
    hg, ag = rng.poisson(lh), rng.poisson(1.1, n)
    P = np.stack([_pois(1.4, 1.1)] * n)
    b, _ = fit_coefficients(P, hg, ag, x[:, None], np.zeros((n, 1)), ridge=1.0)
    assert 0.2 < b[0] < 0.4


def test_transforms_bounds():
    assert spec.short_rest([2, 5, np.nan]).tolist() == [1.0, 0.0, 0.0]
    p, w, hot, cold = spec.weather([20], [30], [50])
    assert p[0] == 1.0 and w[0] == 1.5 and hot[0] == 1.5 and cold[0] == 0
    Xh, Xa = spec.design("lineup", {"A_h": [0.1], "A_a": [-0.2], "C_h": [1], "C_a": [0], "G_h": [0], "G_a": [1]})
    assert Xh.tolist() == [[0.1, 1, 0, 1]] and Xa.tolist() == [[-0.2, 0, 1, 0]]


def test_fotmob_parser_drops_polls_and_odds():
    d = {"general": {"matchId": 1, "homeTeam": {"name": "A"}, "awayTeam": {"name": "B"}},
         "content": {"matchFacts": {"poll": {"oddspoll": {"odds": 1.9}}, "infoBox": {"Stadium": {"lat": 1, "long": 2}}},
                     "lineup": {"lineupType": "predicted", "homeTeam": {"starters": [
                         {"id": 7, "name": "X", "usualPlayingPositionId": 0, "marketValue": 1e7}]}, "awayTeam": {}},
                     "betting": {"odds": 2.0}}}
    out = fotmob.parse_details(d)
    assert out["lineup_status"] == "projected"
    flat = str(out)
    assert "odds" not in flat and "poll" not in flat and "1e7" not in flat and "10000000" not in flat
    assert out["teams"]["home"]["starters"][0]["pos"] == "G"


def test_market_keys_rejected_in_context():
    with pytest.raises(MarketContamination):
        assert_no_market_keys({"lineups": {"home": {"odds": 2.1}}}, "ctx")


def test_name_matching():
    c = {"1": "Amad Diallo Traore", "2": "Cole Palmer", "3": "Moisés Caicedo", "4": "Rodri"}
    assert name_match("Amad Diallo", c) == "1"
    assert name_match("Moises Caicedo", c) == "3"
    assert name_match("C. Palmer", c) == "2" or name_match("Cole Palmer", c) == "2"
    assert name_match("Nobody Here", c) is None


def test_shift_report_sums_to_zero():
    P = _pois(1.5, 1.0)
    s = _shift("x", P / P.sum(), tilt(P, 0.1, -0.1), 0.1, -0.1)
    assert abs(s["d_p_home_pp"] + s["d_p_draw_pp"] + s["d_p_away_pp"]) < 0.02
    assert s["d_p_home_pp"] > 0 > s["d_p_away_pp"]


def test_frozen_stages_never_overwrite(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "FORECAST_DIR", tmp_path)
    base = {"fixture": {"event_id": "E"}, "status": "ok", "simulation": {"p_home": 0.5}}
    proj = dict(base, context={"lineups": {"home": {"status": "projected", "starters": [{"name": "a"}]},
                                           "away": {"status": "projected", "starters": []}},
                               "total_shift": {"d_p_home_pp": 1.0}})
    conf = dict(base, context={"lineups": {"home": {"status": "confirmed", "starters": [{"name": "a"}]},
                                           "away": {"status": "confirmed", "starters": []}},
                               "total_shift": {"d_p_home_pp": 3.0}})
    a, n1 = frozen.freeze("2026-10-31", "E", "v", proj)
    b, n2 = frozen.freeze("2026-10-31", "E", "v", conf)
    c, n3 = frozen.freeze("2026-10-31", "E", "v", proj)
    assert n1 and n2 and not n3
    assert len(list((tmp_path / "2026-10-31" / "E").glob("*.json"))) == 2


def test_last_xi_is_not_confirmed():
    d = {"general": {"matchId": 2}, "content": {"lineup": {"lineupType": "lastStarting11", "homeTeam": {"starters": [
        {"id": 1, "name": "A", "usualPlayingPositionId": 3}]}, "awayTeam": {}}}}
    assert fotmob.parse_details(d)["lineup_status"] == "projected"
    d["content"]["lineup"]["lineupType"] = "standard"
    assert fotmob.parse_details(d)["lineup_status"] == "confirmed"
