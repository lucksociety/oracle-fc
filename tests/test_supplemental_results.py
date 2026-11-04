from oraclefc.ingest.espn_results import parse_results


def test_espn_results_keep_only_completed_regulation_matches():
    event = {
        "date": "2025-10-03T21:00Z",
        "status": {"type": {"name": "STATUS_FULL_TIME"}},
        "odds": {"favorite": "Home"},
        "competitions": [{"competitors": [
            {"homeAway": "away", "team": {"id": "2", "displayName": "Away"}, "score": "1"},
            {"homeAway": "home", "team": {"id": "1", "displayName": "Home"}, "score": "2"},
        ]}],
    }
    other = [{"date": event["date"], "competitions": event["competitions"], "status": {"type": {"name": status}}}
             for status in ("STATUS_IN_PROGRESS", "STATUS_FINAL_PEN", "STATUS_FINAL_AET")]
    rows = list(parse_results({"events": [event, *other]}, "COL", 2025, "fixture"))
    assert len(rows) == 1
    row = rows[0]
    assert (row["home_key"], row["away_key"], row["hg"], row["ag"]) == ("Colombia:espn-1", "Colombia:espn-2", 2, 1)
    assert "odds" not in row
