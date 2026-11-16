"""Polymarket Gamma/CLOB -> internal market records (shapes copied from live Gamma responses, 2026-11-16)."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from oraclefc.market import best_bet as BB
from oraclefc.market import polymarket_prices as PM

H, A = "Germany", "Netherlands"
RULES = "This market refers only to the outcome within the first 90 minutes of regular play plus stoppage time."
FEE = {"exponent": 1, "rate": 0.05, "takerOnly": True, "rebateRate": 0.15}


def gm(mid, typ, slug, outcomes, group="", line=None, **kw):
    return {"id": mid, "sportsMarketType": typ, "slug": "unl-ger-nld-2026-11-16" + slug, "outcomes": json.dumps(outcomes),
            "clobTokenIds": json.dumps([f"{mid}a", f"{mid}b"]), "groupItemTitle": group, "line": line, "description": RULES,
            "conditionId": f"0x{mid}", "volumeNum": 2500.0, "active": True, "closed": False, "acceptingOrders": True,
            "feesEnabled": True, "feeSchedule": FEE, **kw}


def events():
    parent = {"id": "777", "slug": "unl-ger-nld-2026-11-16", "markets": [
        gm(1, "moneyline", "-ger", ["Yes", "No"], "Germany"),
        gm(2, "moneyline", "-draw", ["Yes", "No"], "Draw (Germany vs. Netherlands)"),
        gm(3, "moneyline", "-nld", ["Yes", "No"], "Netherlands")]}
    more = {"id": "778", "slug": "unl-ger-nld-2026-11-16-more-markets", "markets": [
        gm(10, "spreads", "-spread-home-1pt5", [H, A], "Germany (-1.5)", -1.5),
        gm(11, "spreads", "-spread-away-1pt5", [A, H], "Netherlands (-1.5)", -1.5),
        gm(12, "totals", "-total-2pt5", ["Over", "Under"], "O/U 2.5", 2.5),
        gm(13, "both_teams_to_score", "-btts", ["Yes", "No"], "Both Teams to Score"),
        gm(14, "soccer_team_totals", "-team-total-home-1pt5", ["Over", "Under"], "Germany O/U 1.5", 1.5),
        gm(15, "soccer_team_totals", "-team-total-away-0pt5", ["Over", "Under"], "Netherlands O/U 0.5", 0.5),
        gm(16, "first_half_totals", "-first-half-total-0pt5", ["Over", "Under"], "1st Half O/U 0.5", 0.5),
        gm(17, "soccer_first_half_team_totals", "-first-half-team-total-home-0pt5", ["Over", "Under"], "Germany 1st Half O/U 0.5", 0.5),
        gm(18, "totals", "-total-3pt5", ["Over", "Under"], "O/U 3.5", 3.5, acceptingOrders=False),
        gm(19, "totals", "-total-4pt5", ["Over", "Under"], "O/U 4.5", 4.5, closed=True)]}
    exact = {"id": "779", "slug": "unl-ger-nld-2026-11-16-exact-score", "markets": [
        gm(30, "soccer_exact_score", "-exact-score-2-0", ["Yes", "No"], "Germany 2 - 0 Netherlands")]}
    return [parent, more, exact]


def book(ask, bid, size=40.0):
    # CLOB returns asks high->low and bids low->high; best prices are NOT first.
    return {"asks": [{"price": "0.99", "size": "5"}, {"price": f"{ask:.2f}", "size": str(size)}],
            "bids": [{"price": "0.01", "size": "5"}, {"price": f"{bid:.2f}", "size": "10"}], "timestamp": "1794848981561"}


def books():
    raw = {"1a": book(.50, .49), "1b": book(.51, .50), "2a": book(.26, .25), "2b": book(.75, .74), "3a": book(.26, .25), "3b": book(.75, .74),
           "10a": book(.29, .28), "10b": book(.72, .71), "11a": book(.14, .12), "11b": book(.88, .86),
           "12a": book(.63, .62), "12b": book(.38, .37), "13a": book(.70, .69), "13b": book(.31, .30),
           "14a": book(.63, .61), "14b": book(.39, .37), "15a": book(.80, .78), "15b": book(.22, .20),
           "30a": book(.11, .09), "30b": book(.91, .89)}
    return {k: PM.book_quote(v) for k, v in raw.items()}


def test_book_quote_takes_best_levels_and_depth_at_the_ask():
    q = PM.book_quote({"asks": [{"price": "0.63", "size": "100"}, {"price": "0.62", "size": "30"}, {"price": "0.62", "size": "0"}],
                       "bids": [{"price": "0.55", "size": "9"}, {"price": "0.61", "size": "4"}]})
    assert q["ask"] == .62 and q["bid"] == .61 and q["ask_depth"] == 30
    assert PM.book_quote(None) == {"ask": None, "bid": None, "ask_depth": 0, "timestamp": None}
    assert PM.book_quote({"asks": [{"price": "x", "size": "1"}], "bids": []})["ask"] is None


def test_gamma_event_becomes_every_full_time_selection_and_nothing_else():
    ev = PM.adapt_event(events(), H, A, books())
    assert ev["eventId"] == "POLY-777" and ev["isLive"] is False
    sels = {(s["label"], s["side"]): s for s in BB.selections_from_event(ev, H, A)}
    assert all(s["market_id"].startswith("POLY-") and s["regulation_only"] and s["fee"]["rate"] == .05 and s["volume"] == 2500 for s in sels.values())
    expect = {
        ("Germany to win", "YES"): ({"kind": "1x2", "res": "H"}, .50, .49),
        ("Netherlands or draw (NO on Germany)", "NO"): ({"kind": "1x2", "res": "H", "neg": True}, .51, .50),
        ("Draw", "YES"): ({"kind": "1x2", "res": "D"}, .26, .25),
        ("Germany or draw (NO on Netherlands)", "NO"): ({"kind": "1x2", "res": "A", "neg": True}, .75, .74),
        ("Germany -1.5", "YES"): ({"kind": "spread", "team": "home", "hcp": -1.5}, .29, .28),
        ("Netherlands +1.5", "YES"): ({"kind": "spread", "team": "away", "hcp": 1.5}, .72, .71),
        ("Netherlands -1.5", "YES"): ({"kind": "spread", "team": "away", "hcp": -1.5}, .14, .12),
        ("Germany +1.5", "YES"): ({"kind": "spread", "team": "home", "hcp": 1.5}, .88, .86),
        ("Over 2.5 goals", "YES"): ({"kind": "total", "line": 2.5, "over": True}, .63, .62),
        ("Under 2.5 goals", "YES"): ({"kind": "total", "line": 2.5, "over": False}, .38, .37),
        ("Both teams to score", "YES"): ({"kind": "btts"}, .70, .69),
        ("Both teams to score — NO", "NO"): ({"kind": "btts", "neg": True}, .31, .30),
        ("Germany over 1.5 goals", "YES"): ({"kind": "team_total", "team": "home", "line": 1.5, "over": True}, .63, .61),
        ("Germany under 1.5 goals", "YES"): ({"kind": "team_total", "team": "home", "line": 1.5, "over": False}, .39, .37),
        ("Netherlands over 0.5 goals", "YES"): ({"kind": "team_total", "team": "away", "line": 0.5, "over": True}, .80, .78),
        ("Netherlands under 0.5 goals", "YES"): ({"kind": "team_total", "team": "away", "line": 0.5, "over": False}, .22, .20),
        ("Exact score 2-0", "YES"): ({"kind": "exact", "h": 2, "a": 0}, .11, .09),
        ("Any score except 2-0", "NO"): ({"kind": "exact", "h": 2, "a": 0, "neg": True}, .91, .89),
    }
    for key, (outcome, ask, bid) in expect.items():
        assert sels[key]["outcome"] == outcome and sels[key]["ask"] == ask and sels[key]["bid"] == bid, key
    # 3 x 1X2 (YES+NO) + 2 spreads x 2 + total x 2 + BTTS x 2 + 2 team totals x 2 + exact x 2; no halves, closed or paused lines
    assert len(sels) == 6 + 4 + 2 + 2 + 4 + 2


def test_snapshot_shape_matches_what_edge_reads():
    ev = PM.adapt_event(events(), H, A, books())
    mk = PM.parse_event_markets(ev, H, A)
    assert abs(mk["moneyline"]["home"]["mid"] - .495) < 1e-9 and set(mk["moneyline"]) == {"home", "draw", "away"}
    assert abs(mk["totals"][2.5]["p_over"] - .625) < 1e-9 and abs(mk["btts"]["mid"] - .695) < 1e-9 and "2-0" in mk["exact"]


def test_unpriced_missing_or_ambiguous_markets_are_dropped():
    b = books()
    for tok in ("12a", "12b"):
        del b[tok]                                     # no book -> no ask -> not buyable
    evs = events()
    evs[0]["markets"][0]["groupItemTitle"] = "Deutschland"   # name does not match the fixture: never guess
    evs[1]["markets"][0]["outcomes"] = json.dumps(["Germany", "Holland"])
    evs[1]["markets"][4]["slug"] = "unl-ger-nld-2026-11-16-team-total-1pt5"   # side unknown
    labels = {s["label"] for s in BB.selections_from_event(PM.adapt_event(evs, H, A, b), H, A)}
    assert not labels & {"Over 2.5 goals", "Under 2.5 goals", "Germany to win", "Germany -1.5", "Germany over 1.5 goals"}
    assert "Netherlands to win" in labels


def test_fee_schedule_comes_from_the_market():
    assert PM._fee({"feesEnabled": True, "feeSchedule": {"rate": 0.03, "exponent": 1}}) == {"rate": .03, "exponent": 1.0, "source": "market"}
    assert PM._fee({"feesEnabled": False, "feeSchedule": {"rate": 0.05}})["rate"] == 0
    assert PM._fee({}) == {"rate": .05, "exponent": 1.0, "source": "assumed"}   # unknown is never assumed free


def test_live_or_finished_parent_is_flagged():
    evs = events()
    evs[0]["live"] = True
    assert PM.adapt_event(evs, H, A, books())["isLive"] is True


def test_snapshot_fetches_parent_siblings_and_books(monkeypatch, tmp_path):
    calls = []
    evs = events()

    def request(method, url, **kw):
        calls.append((method, url, kw.get("params") or kw.get("json")))
        if url.endswith("/events/777"):
            return evs[0]
        if url.endswith("/events"):
            return [e for e in evs if e["slug"] == kw["params"]["slug"]]
        raw = {**{f"{i}a": book(.50, .49) for i in (1, 2, 3, 10, 11, 12, 13, 14, 15, 30)}, **{f"{i}b": book(.51, .50) for i in (1, 2, 3, 10, 11, 12, 13, 14, 15, 30)}}
        return [{"asset_id": t["token_id"], **raw[t["token_id"]]} for t in kw["json"] if t["token_id"] in raw]
    monkeypatch.setattr(PM, "_request", request)
    monkeypatch.setattr(PM.config, "MARKET_DIR", tmp_path)
    monkeypatch.setattr(PM.time, "sleep", lambda _: None)
    fx = {"POLY-777": {"home_name": H, "away_name": A, "slug": "unl-ger-nld-2026-11-16"},
          "POLY-888": {"home_name": H, "away_name": A, "slug": "other"}}
    snap = PM.snapshot(["POLY-777"], "2026-11-16", fx)
    row = snap["events"]["POLY-777"]
    assert row["fetched_at"] and len(row["selections"]) == 20 and row["moneyline"]["home"]["mid"] == .495
    assert [c[1].rsplit("/", 1)[-1] for c in calls] == ["777", "events", "events", "books"]
    assert not any("jup" in c[1] for c in calls) and (tmp_path / "2026-11-16" / "latest.json").exists()
    # the event behind an id must still be the fixture we forecast
    fx["POLY-777"]["slug"] = "unl-ger-nld-2026-11-17"
    assert "error" in PM.snapshot(["POLY-777"], "2026-11-16", fx)["events"]["POLY-777"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_browser_adapter_matches_python():
    root = Path(__file__).resolve().parent.parent
    evs, b = events(), books()
    evs[1]["markets"][0]["feeSchedule"] = {"rate": 0.03, "exponent": 1}
    evs[1]["markets"][2]["feesEnabled"] = False
    del evs[2]["markets"][0]["feeSchedule"]
    script = ("const P=require(process.argv[1]),B=require(process.argv[2]);const [evs,books,h,a]=JSON.parse(process.argv[3]);"
              "const ev=P.adaptEvent(evs,h,a,books);console.log(JSON.stringify({ev,sels:B.selectionsFromEvent(ev,h,a),"
              "q:P.bookQuote({asks:[{price:'0.63',size:'100'},{price:'0.62',size:'30'}],bids:[{price:'0.55',size:'9'},{price:'0.61',size:'4'}]})}))")
    js = json.loads(subprocess.check_output(["node", "-e", script, str(root / "web/polymarket.js"), str(root / "web/bestbet.js"), json.dumps([evs, b, H, A])]))
    py = PM.adapt_event(evs, H, A, b)
    assert js["ev"] == json.loads(json.dumps(py))
    assert js["sels"] == json.loads(json.dumps(BB.selections_from_event(py, H, A)))
    assert js["q"] == {"ask": .62, "bid": .61, "ask_depth": 30, "timestamp": None}
