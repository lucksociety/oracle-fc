import pandas as pd

from oraclefc.ingest import fotmob_xg as F


def _player(i, name, pos=2, minutes=90, xg=0.1, xa=0.05, sub=None):
    p = {"id": i, "name": name, "usualPlayingPositionId": pos, "positionId": 64}
    if sub:
        p["performance"] = {"substitutionEvents": [sub]}
    stats = {"name": name, "id": i, "stats": [{"key": "top_stats", "stats": {
        "Minutes played": {"key": "minutes_played", "stat": {"value": minutes}},
        "Expected goals (xG)": {"key": "expected_goals", "stat": {"value": xg}},
        "Expected assists (xA)": {"key": "expected_assists", "stat": {"value": xa}},
        "Goals": {"key": "goals", "stat": {"value": 1}},
        "Total shots": {"key": "total_shots", "stat": {"value": 2}},
        "Chances created": {"key": "chances_created", "stat": {"value": 3}}}}]} if minutes else {"name": name, "id": i, "stats": []}
    return p, stats


def _details(mid=555, home="Manchester United", away="Aston Villa"):
    ps, sides = {}, {}
    for key, base in (("homeTeam", 100), ("awayTeam", 200)):
        starters, subs = [], []
        for k in range(11):
            p, st = _player(base + k, f"Player {base + k}", pos=0 if k == 0 else 2)
            starters.append(p); ps[str(p["id"])] = st
        p, st = _player(base + 50, f"Sub {base}", minutes=20); subs.append(p); ps[str(p["id"])] = st
        p, st = _player(base + 51, f"Unused {base}", minutes=0); subs.append(p); ps[str(p["id"])] = st
        sides[key] = {"id": base, "starters": starters, "subs": subs}
    return {"general": {"matchId": str(mid), "finished": True, "matchTimeUTCDate": "2026-11-08T16:30:00.000Z"},
            "header": {"teams": [{"name": home, "score": 4}, {"name": away, "score": 4}]},
            "content": {"lineup": {"lineupType": "standard", **sides}, "playerStats": ps,
                        "stats": {"Periods": {"All": {"stats": [{"key": "top_stats", "stats": [
                            {"key": "expected_goals", "stats": [None, None], "rawStats": [None, None]},
                            {"key": "expected_goals", "stats": ["3.55", "2.88"], "rawStats": [{"value": 3.55}, {"value": 2.88}]},
                            {"key": "odds_should_be_ignored", "rawStats": [{"value": 1.5}, {"value": 2.5}]}]}]}}}}}


def test_parse_match_writes_understat_schema_and_skips_unused_subs():
    match, players = F.parse_match(_details(), "E0", "EPL", 2026)
    assert match["us_id"] == F.OFFSET + 555 and F.is_fotmob(match["us_id"]) and not F.is_fotmob(30000)
    assert (match["hxg"], match["axg"], match["hg"], match["ag"]) == (3.55, 2.88, 4.0, 4.0)
    assert match["datetime"] == pd.Timestamp("2026-11-08 16:30") and match["is_result"] is True
    assert len(players) == 24 and sum(p["position"] == "Sub" for p in players) == 2
    gk = next(p for p in players if p["fm_player_id"] == 100)
    assert gk["position"] == "GK" and gk["time"] == 90 and gk["xG"] == 0.1 and gk["key_passes"] == 3
    assert not any("Unused" in p["player"] for p in players)
    assert set(match) == set(F.MATCH_COLS)


def test_incomplete_pages_are_rejected_not_guessed():
    d = _details(); d["content"]["lineup"]["lineupType"] = "predicted"; assert F.parse_match(d, "E0", "EPL", 2026) is None
    d = _details(); d["general"]["finished"] = False; assert F.parse_match(d, "E0", "EPL", 2026) is None
    d = _details(); d["content"]["stats"]["Periods"]["All"]["stats"][0]["stats"].pop(1); assert F.parse_match(d, "E0", "EPL", 2026) is None
    d = _details(); d["content"]["playerStats"]["105"]["stats"] = []; assert F.parse_match(d, "E0", "EPL", 2026) is None
    d = _details(); d["content"]["lineup"]["homeTeam"]["starters"].pop(); assert F.parse_match(d, "E0", "EPL", 2026) is None


def test_players_keep_their_existing_ids_by_name_within_the_club():
    rows = [{"fm_player_id": 1, "player": "Bruno Fernandes"}, {"fm_player_id": 2, "player": "Brand New Signing"}, {"fm_player_id": 3, "player": "B. Fernandes"}]
    known = {}
    F.assign_ids(rows, {"u77": "Bruno Fernandes", "u78": "Kobbie Mainoo"}, known)
    assert [r["player_id"] for r in rows] == ["u77", "fm2", "fm3"]          # an id is never given to two players in one match
    assert known == {"1": "u77", "2": "fm2", "3": "fm3"}
    again = [{"fm_player_id": 1, "player": "Different Spelling"}]
    F.assign_ids(again, {}, known); assert again[0]["player_id"] == "u77"     # remembered mapping wins


def test_finished_filter_and_superseded_rows():
    body = {"fixtures": {"allMatches": [
        {"id": "1", "status": {"finished": True, "utcTime": "2026-11-08T16:30:00Z", "reason": {"shortKey": "fulltime_short"}}},
        {"id": "2", "status": {"finished": True, "utcTime": "2026-10-20T16:30:00Z", "reason": {"shortKey": "fulltime_short"}}},
        {"id": "3", "status": {"finished": False, "utcTime": "2026-11-21T16:30:00Z"}},
        {"id": "4", "status": {"finished": True, "awarded": True, "utcTime": "2026-11-08T16:30:00Z", "reason": {"shortKey": "fulltime_short"}}}]}}
    assert [x["fm_id"] for x in F.finished(body, pd.Timestamp("2026-11-01 20:00"))] == [1]
    m = pd.DataFrame([
        {"us_id": 30000, "div": "E0", "is_result": True, "datetime": pd.Timestamp("2026-11-08 16:30"), "home": "Manchester United", "away": "Aston Villa"},
        {"us_id": F.OFFSET + 555, "div": "E0", "is_result": True, "datetime": pd.Timestamp("2026-11-08 16:30"), "home": "Manchester United FC", "away": "Aston Villa"},
        {"us_id": F.OFFSET + 556, "div": "E0", "is_result": True, "datetime": pd.Timestamp("2026-11-09 16:30"), "home": "Aston Villa", "away": "Manchester United"}])
    p = pd.DataFrame({"us_id": [30000, F.OFFSET + 555, F.OFFSET + 556]})
    m2, p2 = F.drop_superseded(m, p)
    assert list(m2["us_id"]) == [30000, F.OFFSET + 556] and list(p2["us_id"]) == [30000, F.OFFSET + 556]
