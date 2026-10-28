"""Understat (https://understat.com) — free public xG data for the top-5 European leagues.

Two endpoints (the same JSON the website loads, verified 2026-10-28):
* ``/getLeagueData/{league}/{season}`` -> team xG match histories + match list + player season totals
* ``/getMatchData/{id}``               -> per-match rosters (minutes, position, xG, xA, shots, ...)

Directive Zero: Understat's match list carries a ``forecast`` block (Understat's own
win/draw/loss *prediction*). It is a third-party prediction, so it is dropped here by
allow-list and never stored. Only observed events (goals, shots, xG/xA, minutes) are kept.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from .. import config
from ..governance import assert_no_market_columns
from .http import get_json

BASE = "https://understat.com"
HDR = {"X-Requested-With": "XMLHttpRequest", "Referer": "https://understat.com/"}
# understat league -> football-data division
LEAGUES = {"EPL": "E0", "La_liga": "SP1", "Bundesliga": "D1", "Serie_A": "I1", "Ligue_1": "F1"}
RAW = config.RAW_DIR / "understat"
MATCH_FIELDS = ["id", "isResult", "datetime"]
ROSTER_FIELDS = {"player_id": str, "player": str, "position": str, "positionOrder": int, "time": int,
                 "xG": float, "xA": float, "goals": int, "assists": int, "shots": int, "key_passes": int,
                 "roster_in": str, "roster_out": str, "red_card": int, "own_goals": int}


def current_season() -> int:
    t = pd.Timestamp.now()
    return t.year if t.month >= 7 else t.year - 1


def league_data(league: str, season: int):
    fresh = season >= current_season()
    return get_json(f"{BASE}/getLeagueData/{league}/{season}", RAW / f"league_{league}_{season}.json",
                    max_age_h=6 if fresh else None, headers=HDR)


def matches(seasons=range(2019, 2100)) -> pd.DataFrame:
    rows = []
    for lg, div in LEAGUES.items():
        for s in seasons:
            if s > current_season():
                break
            d = league_data(lg, s)
            if not d:
                continue
            for m in d.get("dates", []):
                # explicit allow-list: never copy m["forecast"]
                rows.append({"us_id": int(m["id"]), "league": lg, "div": div, "season": s,
                             "datetime": pd.Timestamp(m["datetime"]), "is_result": bool(m["isResult"]),
                             "home": m["h"]["title"], "away": m["a"]["title"],
                             "hg": _num(m["goals"]["h"]), "ag": _num(m["goals"]["a"]),
                             "hxg": _num(m["xG"]["h"]), "axg": _num(m["xG"]["a"])})
    df = pd.DataFrame(rows)
    assert_no_market_columns(df, "understat matches")
    return df


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return float("nan")


def match_rosters(us_id: int):
    return get_json(f"{BASE}/getMatchData/{us_id}", RAW / "matches" / f"{us_id}.json", max_age_h=None, headers=HDR)


def rosters(match_ids, workers: int = 8) -> pd.DataFrame:
    def one(mid):
        d = match_rosters(mid)
        out = []
        if not d or "rosters" not in d:
            return out
        for side in ("h", "a"):
            for r in (d["rosters"].get(side) or {}).values():
                rec = {"us_id": int(mid), "side": side, "team_id": r.get("team_id")}
                for k, typ in ROSTER_FIELDS.items():
                    v = r.get(k)
                    try:
                        rec[k] = typ(v) if v is not None else None
                    except ValueError:
                        rec[k] = None
                out.append(rec)
        return out

    rows = []
    with ThreadPoolExecutor(workers) as ex:
        for i, part in enumerate(ex.map(one, list(match_ids))):
            rows.extend(part)
            if i % 1000 == 0:
                print(f"   understat rosters {i}", flush=True)
    df = pd.DataFrame(rows)
    assert_no_market_columns(df, "understat rosters")
    return df


def build(seasons=range(2019, 2100)):
    m = matches(seasons)
    done = m[m["is_result"]]
    r = rosters(done["us_id"].tolist())
    config.CLEAN_DIR.mkdir(parents=True, exist_ok=True)
    config.CONTEXT_DIR.mkdir(parents=True, exist_ok=True)
    m.to_parquet(config.CONTEXT_DIR / "understat_matches.parquet", index=False)
    r.to_parquet(config.CONTEXT_DIR / "understat_players.parquet", index=False)
    print(f"understat: {len(m)} matches ({len(done)} played), {len(r)} player-match rows")
    return m, r


def update(max_age_h: float = 3.0):
    """Incremental refresh for the pipeline: re-read the current season's fixture lists and
    fetch rosters only for played matches not yet in the committed snapshot."""
    pm = config.CONTEXT_DIR / "understat_matches.parquet"
    pp = config.CONTEXT_DIR / "understat_players.parquet"
    if not pm.exists() or not pp.exists():
        return build()
    old_m, old_p = pd.read_parquet(pm), pd.read_parquet(pp)
    cur = current_season()
    new_m = matches(range(cur - 1, cur + 1))
    m = pd.concat([old_m[~old_m["us_id"].isin(new_m["us_id"])], new_m], ignore_index=True)
    have = set(old_p["us_id"].unique())
    todo = [i for i in m.loc[m["is_result"], "us_id"] if i not in have]
    r = rosters(todo) if todo else old_p.iloc[:0]
    p = pd.concat([old_p, r], ignore_index=True) if len(r) else old_p
    m.to_parquet(pm, index=False)
    p.to_parquet(pp, index=False)
    print(f"understat update: {len(todo)} new played matches, {len(r)} player rows added")
    return m, p


if __name__ == "__main__":
    build()
