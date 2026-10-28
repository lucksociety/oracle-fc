from oraclefc.market.edge import compute_edges
from oraclefc.market.jupiter_prices import parse_event_markets


def _m(t, title, buy, sell, **kw):
    return {"sportsMarketType": t, "title": title, "status": "open", "isTeamMarket": kw.get("team", False),
            "sportsLine": kw.get("line"), "pricing": {"buyYesPriceUsd": buy, "sellYesPriceUsd": sell}}


def test_parse_and_edge():
    ev = {"markets": [_m("moneyline", "A FC", 540000, 530000), _m("moneyline", "Draw", 250000, 240000),
                      _m("moneyline", "B FC", 230000, 220000), _m("both_teams_to_score", "BTTS", 620000, 600000),
                      _m("totals", "Over", 610000, 600000, team=True, line=2.5),
                      _m("totals", "Under", 1000000, 0, team=True, line=7.5),
                      _m("soccer_exact_score", "A FC 1 - 1 B FC", 120000, 100000)]}
    mk = parse_event_markets(ev, "A FC", "B FC")
    assert abs(mk["moneyline"]["home"]["mid"] - 0.535) < 1e-9
    assert mk["totals"][2.5]["p_over"] == 0.605 and 7.5 not in mk["totals"]
    grid = [[0.0] * 11 for _ in range(11)]
    grid[1][1] = 0.12
    fc = {"fixture": {"event_id": "E", "home_name": "A FC", "away_name": "B FC"},
          "simulation": {"p_home": 0.6, "p_draw": 0.2, "p_away": 0.2, "btts": 0.5,
                         "totals_over": {"over_2.5": 0.55}, "top_scores": [], "score_grid": grid}}
    e = compute_edges(fc, mk)
    r = {(x["market"], x["selection"]): x for x in e["rows"]}
    assert abs(r[("1X2", "A FC")]["edge_vs_mid"] - 0.065) < 1e-9
    assert abs(r[("Total", "Over 2.5")]["edge_vs_mid"] - (0.55 - 0.605)) < 1e-9
    assert abs(r[("Exact score", "1-1")]["edge_vs_mid"] - (0.12 - 0.11)) < 1e-9
