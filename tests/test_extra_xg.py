"""Team xG for leagues outside the top five: linking, point-in-time use, and routine updates."""
import pandas as pd

from oraclefc.context import history as H
from oraclefc.ingest import fotmob, fotmob_xg


def _results():
    return pd.DataFrame({"div": ["BRA", "BRA"], "country": ["Brazil", "Brazil"], "home": ["Vasco", "Santos"], "away": ["Santos", "Vasco"],
                         "home_key": ["Brazil:Vasco", "Brazil:Santos"], "away_key": ["Brazil:Santos", "Brazil:Vasco"],
                         "date": pd.to_datetime(["2026-05-02", "2026-09-10"]), "match_id": ["m1", "m2"]})


def _xg(tmp_path, monkeypatch):
    rows = pd.DataFrame({"us_id": [fotmob_xg.OFFSET + 1, fotmob_xg.OFFSET + 2], "league": "BRA", "div": "BRA", "season": 2026,
                         "datetime": pd.to_datetime(["2026-05-03 00:30", "2026-09-10 22:00"]), "is_result": True,
                         "home": ["Vasco da Gama", "Santos"], "away": ["Santos", "Vasco da Gama"], "hg": [1.0, 0.0], "ag": [1.0, 2.0],
                         "hxg": [1.7, 0.6], "axg": [0.9, 1.4]})
    path = tmp_path / "extra.parquet"
    rows.to_parquet(path, index=False)
    monkeypatch.setattr(fotmob_xg, "EXTRA_M", path)
    return rows


def test_alias_links_fotmob_club_names_and_late_kickoffs(tmp_path, monkeypatch):
    _xg(tmp_path, monkeypatch)
    mp = H.map_extra_xg(_results())
    assert list(mp.sort_values("us_id")["match_id"]) == ["m1", "m2"]  # "Vasco da Gama" -> "Vasco"; 00:30 UTC kick-off is the day before
    df = H.attach_xg(_results(), H.xg_rows(_results(), None))
    assert list(df["hxg"]) == [1.7, 0.6]


def test_extra_xg_is_point_in_time(tmp_path, monkeypatch):
    _xg(tmp_path, monkeypatch)
    df = H.attach_xg(_results(), H.xg_rows(_results(), None, pd.Timestamp("2026-06-01")))
    assert df["hxg"].notna().tolist() == [True, False]


def test_routine_update_adds_only_new_finished_matches(tmp_path, monkeypatch):
    _xg(tmp_path, monkeypatch)
    old = pd.Timestamp("2026-09-11 22:00:00+00:00")
    fixtures = [{"id": 2, "status": {"finished": True, "utcTime": "2026-09-10T22:00:00Z", "reason": {"shortKey": "fulltime_short"}}},
                {"id": 3, "status": {"finished": True, "utcTime": old.isoformat(), "reason": {"shortKey": "fulltime_short"}}},
                {"id": 4, "status": {"finished": False, "utcTime": "2026-12-01T22:00:00Z"}},
                {"id": 5, "status": {"finished": True, "utcTime": "2026-03-01T22:00:00Z", "reason": {"shortKey": "fulltime_short"}}}]
    asked = []
    monkeypatch.setattr(fotmob, "_season_list", lambda lid: ["2026", "2025", "2024", "2023", "2022"])
    monkeypatch.setattr(fotmob, "league", lambda lid, s, max_age_h=None: {"fixtures": {"allMatches": fixtures if s == "2026" else []}})
    monkeypatch.setattr(fotmob, "match_details_raw", lambda mid, max_age_h=None: asked.append(mid) or {"id": mid})
    row = {"us_id": fotmob_xg.OFFSET + 3, "league": "BRA", "div": "BRA", "season": 2026, "datetime": old.tz_localize(None), "is_result": True,
           "home": "Santos", "away": "Flamengo", "hg": 1.0, "ag": 0.0, "hxg": 1.1, "axg": 0.8}
    monkeypatch.setattr(fotmob_xg, "parse_match", lambda d, div, league, season: (row, []))
    m = fotmob_xg.fill_extra({"BRA": 2023}, max_seconds=None)
    assert asked == [3]            # 2 is stored, 4 is unfinished, 5 is older than the look-back window
    assert len(m) == 3 and len(pd.read_parquet(fotmob_xg.EXTRA_M)) == 3
