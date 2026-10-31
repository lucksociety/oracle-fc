from oraclefc.market.edge import lock_pre_kickoff
from oraclefc.market.grade import bet_pnl, find_result, forecast_metrics, parse_label, settle

H, A = "Santos FC", "SE Palmeiras"


def test_parse_and_settle_labels():
    cases = [("SE Palmeiras under 1.5 goals", (0, 0), True), ("SE Palmeiras under 1.5 goals", (0, 2), False),
             ("Under 2.5 goals", (2, 1), False), ("Over 2.5 goals", (2, 1), True),
             ("Both teams to score — NO", (2, 0), True), ("Both teams to score", (2, 0), False),
             ("Draw", (1, 1), True), ("Either team to win (NO on draw)", (1, 1), False),
             (f"{A} or draw (NO on {H})", (0, 0), True), (f"{H} or draw (NO on {A})", (0, 1), False),
             (f"{H} to win", (1, 0), True), (f"{A} +1.5", (2, 1), True), (f"{A} +1.5", (3, 1), False),
             ("Exact score 1-1", (1, 1), True), ("Any score except 1-1", (1, 1), False),
             ("NO — Under 2.5 goals", (2, 1), True)]
    for label, (hg, ag), want in cases:
        spec = parse_label(label, H, A)
        assert spec is not None, label
        assert settle(spec, hg, ag) is want, label


def test_pnl_uses_cost_including_fee():
    bet = {"ask": 0.5, "fee_per_contract": 0.0225, "cost_per_contract": 0.5225}
    assert abs(bet_pnl(bet, True) - (1 / 0.5225 - 1)) < 1e-12
    assert bet_pnl(bet, False) == -1.0


def test_lock_keeps_pre_kickoff_verdict():
    ko = "2026-10-28T22:30:00+00:00"
    prev = {"E1": {"event_id": "E1", "kickoff_utc": ko, "priced_at": "2026-10-28T21:55:00+00:00",
                   "verdict": "BET", "bet": {"label": "Under 2.5 goals"}}}
    new = [{"event_id": "E1", "kickoff_utc": ko, "priced_at": "2026-10-29T01:00:00+00:00", "verdict": "NO BET",
            "reason": "prices were fetched after kick-off (in-play), not pre-match"}]
    out = lock_pre_kickoff(new, prev)
    assert out[0]["verdict"] == "BET" and out[0]["locked"]
    # a newer PRE-kick-off snapshot replaces the earlier one
    new2 = [{"event_id": "E1", "kickoff_utc": ko, "priced_at": "2026-10-28T22:20:00+00:00", "verdict": "NO BET"}]
    assert lock_pre_kickoff(new2, prev)[0]["verdict"] == "NO BET"


def test_find_result_matches_names_and_time():
    fx = {"home_name": "Manchester City FC", "away_name": "Brighton & Hove Albion FC", "home_matched": "Man City",
          "away_matched": "Brighton", "kickoff_utc": "2026-10-28T19:30:00+00:00"}
    res = [{"home": "Manchester United", "away": "Brighton & Hove Albion", "utc": "2026-10-28T19:30:00.000Z"},
           {"home": "Manchester City", "away": "Brighton & Hove Albion", "utc": "2026-10-28T19:30:00.000Z"},
           {"home": "Manchester City", "away": "Brighton & Hove Albion", "utc": "2026-11-28T19:30:00.000Z"}]
    assert find_result(fx, res) is res[1]
    assert find_result({**fx, "kickoff_utc": "2026-10-20T19:30:00+00:00"}, res) is None


def test_forecast_metrics():
    sim = {"p_home": 0.5, "p_draw": 0.3, "p_away": 0.2, "modal_score": {"home": 1, "away": 0},
           "top_scores": [{"home": 1, "away": 0}, {"home": 1, "away": 1}], "xg_total": 2.5}
    m = forecast_metrics(sim, 1, 0)
    assert m["exact_hit"] and m["top5_hit"] and m["outcome"] == "H"
    assert abs(m["rps"] - ((0.5 - 1) ** 2 + (0.8 - 1) ** 2) / 2) < 1e-12


def test_corrected_identity_still_grades_original_espanyol_fixture():
    fx={'home_name':'Villarreal CF','away_name':'RCD Espanyol de Barcelona','home_matched':'Villarreal',
        'away_matched':'Barcelona','kickoff_utc':'2026-10-30T20:00:00+00:00'}
    actual={'home':'Villarreal','away':'Espanyol','utc':'2026-10-30T20:00:00Z'}
    assert find_result(fx,[actual]) is actual
