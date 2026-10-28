"""FotMob public JSON (the endpoints www.fotmob.com itself loads; no key; verified 2026-10-28).

Used for *non-market* match context only:
* league seasons  -> team ids, exact UTC kickoff times (historical & upcoming)
* team pages      -> home venue name + latitude/longitude (weather + travel)
* match details   -> projected/confirmed lineups, unavailable players (injury/suspension,
                     expected return), stadium coordinates.

Directive Zero: FotMob match pages also carry an odds poll ("oddspoll"), betting
insights and fan "who will win" votes. Those blocks are never read: every parser
below copies an explicit allow-list of fields only, and the result is checked by
``assert_no_market_keys``.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pandas as pd

from .. import config
from ..governance import assert_no_market_keys
from ..teams import match_team, team_key
from .http import get_json

BASE = "https://www.fotmob.com/api/data"
RAW = config.RAW_DIR / "fotmob"

# football-data division -> FotMob league id
LEAGUES = {
    "E0": 47, "E1": 48, "E2": 108, "E3": 109, "EC": 117, "SC0": 64, "SC1": 123, "SC2": 124, "SC3": 125,
    "D1": 54, "D2": 146, "I1": 55, "I2": 86, "SP1": 87, "SP2": 140, "F1": 53, "F2": 110, "N1": 57,
    "B1": 40, "P1": 61, "T1": 71, "G1": 135, "ARG": 112, "AUT": 38, "BRA": 268, "CHN": 120, "DNK": 46,
    "FIN": 51, "IRL": 126, "JPN": 223, "MEX": 230, "NOR": 59, "POL": 196, "ROU": 189, "SWE": 67,
    "SWZ": 69, "USA": 130,
}
UCL_ID = 42
# FotMob positionId groups (first digit / magnitude): 11 = GK, 3x = DEF, 6x/7x = MID, 8x/10x = FWD
# usualPlayingPositionId: 0 GK, 1 DEF, 2 MID, 3 FWD


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def league(lid: int, season: str | None = None, max_age_h: float | None = 12):
    tag = (season or "current").replace("/", "-")
    p = {"id": lid}
    if season:
        p["season"] = season
    return get_json(f"{BASE}/leagues", RAW / "leagues" / f"{lid}_{tag}.json",
                    max_age_h=max_age_h, params=p)


def team(tid: int, max_age_h: float | None = 24 * 30):
    return get_json(f"{BASE}/teams", RAW / "teams" / f"{tid}.json", max_age_h=max_age_h, params={"id": tid})


def matches_on(date: str, max_age_h: float = 1.0):
    """All matches FotMob lists on a calendar date (YYYY-MM-DD, FotMob's UTC day)."""
    return get_json(f"{BASE}/matches", RAW / "days" / f"{date}.json", max_age_h=max_age_h,
                    params={"date": date.replace("-", "")})


def match_details_raw(mid: int, max_age_h: float = 0.5):
    return get_json(f"{BASE}/matchDetails", RAW / "match" / f"{mid}.json", max_age_h=max_age_h,
                    params={"matchId": mid})


# ------------------------------------------------------------------ parsing (allow-list)
def _pos_group(p: dict) -> str:
    u = p.get("usualPlayingPositionId")
    if u in (0, 1, 2, 3):
        return "GDMF"[u]
    pid = p.get("positionId")
    if not pid:
        return None
    if pid == 11:
        return "G"
    if pid < 60:
        return "D"
    if pid < 80:
        return "M"
    return "F"


def _player(p: dict) -> dict:
    return {"fm_id": p.get("id"), "name": p.get("name"), "pos": _pos_group(p),
            "shirt": p.get("shirtNumber")}


def parse_details(d: dict) -> dict | None:
    """Return the allow-listed context of one FotMob match (no polls / odds / insights)."""
    if not d or "content" not in d:
        return None
    gen = d.get("general", {})
    info = ((d["content"].get("matchFacts") or {}).get("infoBox") or {})
    st = info.get("Stadium") or {}
    L = d["content"].get("lineup") or {}
    lt = L.get("lineupType")
    # FotMob lineupType: "standard" = official team sheet; "predicted" = enetpulse projection;
    # "lastStarting11" = the side's previous XI (a naive projection); "unavailable" = none.
    status = {"standard": "confirmed", "predicted": "projected", "lastStarting11": "projected"}.get(lt, "none")
    if lt == "standard" and not (L.get("homeTeam") or {}).get("starters"):
        status = "none"
    sides = {}
    for side in ("homeTeam", "awayTeam"):
        t = L.get(side) or {}
        sides["home" if side == "homeTeam" else "away"] = {
            "fm_team_id": t.get("id"), "name": t.get("name"), "formation": t.get("formation"),
            "starters": [_player(p) for p in t.get("starters") or []],
            "bench": [_player(p) for p in t.get("subs") or []],
            "unavailable": [{**_player(p), "type": (p.get("unavailability") or {}).get("type"),
                             "expected_return": (p.get("unavailability") or {}).get("expectedReturn")}
                            for p in t.get("unavailable") or []],
        }
    out = {"fm_match_id": int(gen.get("matchId") or 0), "kickoff_utc": (info.get("Match Date") or {}).get("utcTime"),
           "home_name": (gen.get("homeTeam") or {}).get("name"), "away_name": (gen.get("awayTeam") or {}).get("name"),
           "league_id": gen.get("leagueId"), "league_name": gen.get("leagueName"),
           "venue": {"name": st.get("name"), "city": st.get("city"), "lat": st.get("lat"), "lon": st.get("long")},
           "lineup_status": status,
           "lineup_source": "FotMob" + {"predicted": " projected XI (enetpulse)", "lastStarting11": " — previous match XI "
                                        "(no projection published yet)", "standard": " official team sheet"}.get(lt, ""),
           "teams": sides, "fetched_at": _now(),
           "source_url": f"https://www.fotmob.com/match/{gen.get('matchId')}"}
    assert_no_market_keys(out, "fotmob match context")
    return out


def match_context(mid: int, max_age_h: float = 0.5) -> dict | None:
    return parse_details(match_details_raw(mid, max_age_h))


def day_fixtures(date: str) -> list[dict]:
    d = matches_on(date)
    rows = []
    for lg in (d or {}).get("leagues", []):
        for m in lg.get("matches", []):
            rows.append({"fm_match_id": int(m["id"]), "league_id": lg.get("primaryId") or lg.get("id"),
                         "league_name": lg.get("name"), "ccode": lg.get("ccode"),
                         "home": m["home"].get("longName") or m["home"]["name"], "home_id": m["home"]["id"],
                         "away": m["away"].get("longName") or m["away"]["name"], "away_id": m["away"]["id"],
                         "utc": (m.get("status") or {}).get("utcTime")})
    return rows


# ------------------------------------------------------------------ venues / kickoffs (history)
def _season_list(lid: int) -> list[str]:
    d = league(lid, None)
    return list((d or {}).get("allAvailableSeasons") or [])


def build_venues(df: pd.DataFrame, first_year: int = 2020, workers: int = 4):
    """Map FotMob teams to our team keys per division (date-bounded candidates), fetch each
    team's home venue coordinates, and keep FotMob UTC kickoffs for historical fixtures."""
    jobs = []
    for div, lid in LEAGUES.items():
        for s in _season_list(lid):
            if int(s[:4]) >= first_year:
                jobs.append((div, lid, s))
    with ThreadPoolExecutor(workers) as ex:
        leagues = list(ex.map(lambda j: (j, league(j[1], j[2], None if not _is_current(j[2]) else 12)), jobs))
    team_rows, fx_rows = [], []
    for (div, lid, s), d in leagues:
        if not d:
            continue
        ms = (d.get("fixtures") or {}).get("allMatches") or []
        if not ms:
            continue
        utc = pd.to_datetime([m["status"]["utcTime"] for m in ms], utc=True, errors="coerce")
        lo, hi = utc.min().tz_localize(None) - pd.Timedelta(days=20), utc.max().tz_localize(None) + pd.Timedelta(days=20)
        sub = df[(df["div"] == div) & (df["date"] >= lo) & (df["date"] <= hi)]
        cands = sorted(set(sub["home"]) | set(sub["away"]))
        country = config.ALL_DIVISIONS[div][0]
        names = {}
        for m in ms:
            for side in ("home", "away"):
                names[int(m[side]["id"])] = m[side]["name"]
        mapping = {}
        for tid, nm in names.items():
            mt = match_team(nm, cands)
            mapping[tid] = team_key(country, mt.canonical) if mt.canonical else None
            team_rows.append({"div": div, "season": s, "fm_team_id": tid, "fm_name": nm,
                              "team_key": mapping[tid], "method": mt.method})
        for m, t in zip(ms, utc):
            fx_rows.append({"div": div, "fm_season": s, "fm_match_id": int(m["id"]), "utc": t,
                            "home_key": mapping.get(int(m["home"]["id"])), "away_key": mapping.get(int(m["away"]["id"])),
                            "finished": bool(m["status"].get("finished"))})
    teams_df = pd.DataFrame(team_rows)
    ids = sorted(teams_df["fm_team_id"].unique())
    with ThreadPoolExecutor(workers) as ex:
        tds = list(ex.map(team, ids))
    ven = []
    for tid, td in zip(ids, tds):
        v = (((td or {}).get("overview") or {}).get("venue") or {}).get("widget") or {}
        loc = v.get("location") or [None, None]
        try:
            lat, lon = float(loc[0]), float(loc[1])
        except (TypeError, ValueError):
            lat = lon = None
        ven.append({"fm_team_id": tid, "venue": v.get("name"), "city": v.get("city"), "lat": lat, "lon": lon})
    ven = pd.DataFrame(ven)
    teams_df = teams_df.merge(ven, on="fm_team_id", how="left")
    fx = pd.DataFrame(fx_rows)
    config.CLEAN_DIR.mkdir(parents=True, exist_ok=True)
    teams_df.to_parquet(config.CONTEXT_DIR / "fotmob_teams.parquet", index=False)
    fx.to_parquet(config.CLEAN_DIR / "fotmob_fixtures.parquet", index=False)
    print(f"fotmob: {len(teams_df)} team-seasons, {teams_df['team_key'].notna().mean():.1%} mapped, "
          f"{ven['lat'].notna().mean():.1%} venues with coords, {len(fx)} fixtures")
    return teams_df, fx


def _is_current(season: str) -> bool:
    y = pd.Timestamp.now().year
    return str(y) in season or str(y + 1) in season


if __name__ == "__main__":
    from .. import store
    build_venues(store.load())
