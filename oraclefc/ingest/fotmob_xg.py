"""FotMob stand-in for Understat's match xG and player rows (top-5 leagues).

Understat stopped answering the pipeline on 2026-11-02 (every URL returns its error page), so the
xG blended into the fit and the player book behind the line-up features stopped updating. FotMob
match pages carry the same observations: team xG, and per-player minutes, xG and xA. Rows are
written in Understat's schema so nothing downstream changes:

* match ids are ``OFFSET + FotMob match id`` so they can never collide with Understat ids;
* players are mapped to their existing Understat ids by name within the same club, so ratings and
  minutes shares carry on; a player with no match keeps a stable ``fm<id>`` id;
* if Understat later returns the same match, the FotMob copy is dropped.

Observed values only. No odds, ratings-as-predictions or forecasts are read.
"""
from __future__ import annotations

import json
import time

import pandas as pd

from .. import config
from ..governance import assert_no_market_columns
from ..teams import match_team
from . import fotmob

OFFSET = 10_000_000_000
LEAGUES = {"E0": ("EPL", 47), "SP1": ("La_liga", 87), "D1": ("Bundesliga", 54), "I1": ("Serie_A", 55), "F1": ("Ligue_1", 53)}
ID_MAP = config.CONTEXT_DIR / "fotmob_player_ids.json"
# FotMob's xG ran 4.6% below Understat's on the 107 October 2026 matches both covered (correlation 0.93), so it is
# scaled up to keep one consistent series for the fit and the player ratings.
XG_SCALE = 1.048
POS = {"G": "GK", "D": "DC", "M": "MC", "F": "FW"}
# FotMob club names that the shared matcher does not link to Understat's titles (checked against all five leagues).
CLUB_ALIASES = {"1. FC Köln": "FC Cologne", "RB Leipzig": "RasenBallsport Leipzig"}


def club_title(name: str, titles: list[str]):
    alias = CLUB_ALIASES.get(name)
    return alias if alias in titles else match_team(name, titles).canonical


MATCH_COLS = ["us_id", "league", "div", "season", "datetime", "is_result", "home", "away", "hg", "ag", "hxg", "axg"]


def is_fotmob(us_id) -> bool:
    return int(us_id) >= OFFSET


def finished(body: dict, since: pd.Timestamp) -> list[dict]:
    """Regulation-finished league matches kicked off after ``since`` (naive UTC)."""
    out = []
    for m in ((body or {}).get("fixtures") or {}).get("allMatches", []):
        s = m.get("status") or {}
        if s.get("finished") is not True or s.get("cancelled") or s.get("awarded") or (s.get("reason") or {}).get("shortKey") != "fulltime_short":
            continue
        try:
            t = pd.Timestamp(s["utcTime"]).tz_convert("UTC").tz_localize(None)
            mid = int(m["id"])
        except (KeyError, TypeError, ValueError):
            continue
        if t > since:
            out.append({"fm_id": mid, "datetime": t})
    return out


def _stat(block: dict, key: str):
    for s in (block or {}).get("stats", {}).values() if isinstance((block or {}).get("stats"), dict) else []:
        if s.get("key") == key:
            v = (s.get("stat") or {}).get("value")
            return float(v) if isinstance(v, (int, float)) else None
    return None


def team_xg(details: dict):
    """(home xG, away xG) from the full-match team statistics, or None."""
    periods = ((details.get("content") or {}).get("stats") or {}).get("Periods") or {}
    for grp in (periods.get("All") or {}).get("stats") or []:
        for s in (grp or {}).get("stats") or []:
            raw = s.get("rawStats") or []
            if s.get("key") == "expected_goals" and len(raw) == 2 and all(isinstance(x, dict) and isinstance(x.get("value"), (int, float)) for x in raw):
                return float(raw[0]["value"]), float(raw[1]["value"])
    return None


def parse_match(details: dict, div: str, league: str, season: int):
    """One finished FotMob match -> (match row, player rows) in Understat's schema, or None if incomplete."""
    gen, content = details.get("general") or {}, details.get("content") or {}
    teams, xg, lineup, stats = (details.get("header") or {}).get("teams") or [], team_xg(details), content.get("lineup") or {}, content.get("playerStats") or {}
    if gen.get("finished") is not True or len(teams) != 2 or xg is None or lineup.get("lineupType") != "standard":
        return None
    try:
        mid = int(gen["matchId"]); when = pd.Timestamp(gen["matchTimeUTCDate"]).tz_convert("UTC").tz_localize(None)
        hg, ag = int(teams[0]["score"]), int(teams[1]["score"])
    except (KeyError, TypeError, ValueError):
        return None
    match = {"us_id": OFFSET + mid, "league": league, "div": div, "season": season, "datetime": when, "is_result": True,
             "home": teams[0]["name"], "away": teams[1]["name"], "hg": float(hg), "ag": float(ag), "hxg": round(xg[0] * XG_SCALE, 4), "axg": round(xg[1] * XG_SCALE, 4)}
    players = []
    for side, key in (("h", "homeTeam"), ("a", "awayTeam")):
        t = lineup.get(key) or {}
        if len(t.get("starters") or []) != 11:
            return None
        for group, rows in (("start", t.get("starters") or []), ("sub", t.get("subs") or [])):
            for order, p in enumerate(rows, 1):
                top = next((b for b in (stats.get(str(p.get("id"))) or {}).get("stats", []) if b.get("key") == "top_stats"), None)
                minutes = _stat(top, "minutes_played")
                if not p.get("id") or not p.get("name") or not minutes or minutes <= 0:
                    if group == "start":
                        return None          # a starter without minutes means the page is incomplete
                    continue                 # unused substitute
                players.append({"us_id": OFFSET + mid, "side": side, "team_id": str(t.get("id")), "fm_player_id": int(p["id"]), "player": str(p["name"]),
                                "position": POS.get(fotmob._pos_group(p) or "M", "MC") if group == "start" else "Sub",
                                "positionOrder": order if group == "start" else 17, "time": int(minutes),
                                "xG": round((_stat(top, "expected_goals") or 0.0) * XG_SCALE, 4), "xA": round((_stat(top, "expected_assists") or 0.0) * XG_SCALE, 4),
                                "goals": int(_stat(top, "goals") or 0), "assists": int(_stat(top, "assists") or 0),
                                "shots": int(_stat(top, "total_shots") or 0), "key_passes": int(_stat(top, "chances_created") or 0),
                                "roster_in": "0", "roster_out": "0", "red_card": 0, "own_goals": 0})
    return match, players


def _norm(s):
    from ..context.live import _norm as n
    return n(s)


def assign_ids(players: list[dict], club_players: dict, known: dict) -> None:
    """Give each FotMob player an Understat id (by name within the club) or a stable fm<id>. Mutates rows and ``known``."""
    from ..context.live import name_match
    used = set()
    for r in players:
        fid = str(r.pop("fm_player_id"))
        pid = known.get(fid)
        if pid is None:
            pid = name_match(r["player"], {p: n for p, n in club_players.items() if p not in used}) or f"fm{fid}"
            known[fid] = pid
        used.add(pid)
        r["player_id"] = str(pid)


def club_rosters(matches: pd.DataFrame, players: pd.DataFrame, div: str, days: int = 500) -> dict:
    """Understat club title -> {player_id: name} from that club's recent matches."""
    m = matches[(matches["div"] == div) & matches["is_result"]]
    m = m[m["datetime"] >= m["datetime"].max() - pd.Timedelta(days=days)]
    p = players.merge(m[["us_id", "home", "away"]], on="us_id", how="inner")
    p = p.assign(club=p["home"].where(p["side"] == "h", p["away"]))
    return {club: dict(zip(g["player_id"].astype(str), g["player"])) for club, g in p.groupby("club")}


def drop_superseded(matches: pd.DataFrame, players: pd.DataFrame):
    """Remove a FotMob match once Understat has the same fixture (same division, home club, within a day)."""
    fm = matches[matches["us_id"] >= OFFSET]
    us = matches[(matches["us_id"] < OFFSET) & matches["is_result"]]
    drop = []
    for div, g in fm.groupby("div"):
        u = us[us["div"] == div]
        titles = sorted(set(u["home"]) | set(u["away"]))
        for r in g.itertuples():
            home = club_title(r.home, titles)
            if home is not None and ((u["home"] == home) & ((u["datetime"] - r.datetime).abs() <= pd.Timedelta(days=1))).any():
                drop.append(r.us_id)
    if not drop:
        return matches, players
    return matches[~matches["us_id"].isin(drop)], players[~players["us_id"].isin(drop)]


def fill(matches: pd.DataFrame, players: pd.DataFrame, season: int, max_seconds: float | None = 150.0, max_matches: int = 400):
    """Append FotMob rows for top-5 matches played after the last Understat-recorded match of each league."""
    deadline = None if max_seconds is None else time.monotonic() + max_seconds
    try:
        known = json.loads(ID_MAP.read_text())
    except (OSError, ValueError):
        known = {}
    have = set(matches["us_id"])
    new_m, new_p, skipped = [], [], 0
    for div, (league, lid) in LEAGUES.items():
        real = matches[(matches["div"] == div) & matches["is_result"] & (matches["us_id"] < OFFSET)]
        since = real["datetime"].max() + pd.Timedelta(hours=3) if len(real) else pd.Timestamp("2000-01-01")
        todo = [x for x in finished(fotmob.league(lid, max_age_h=6), since) if OFFSET + x["fm_id"] not in have]
        if not todo:
            continue
        rosters = club_rosters(matches, players, div)
        titles = sorted(rosters)
        for x in sorted(todo, key=lambda x: x["datetime"])[:max_matches]:
            if deadline is not None and time.monotonic() > deadline:
                skipped += 1
                continue
            # The pipeline caches match pages before kick-off for line-ups. Only accept a copy fetched after full time.
            hours_since_end = (pd.Timestamp.now(tz="UTC").tz_localize(None) - x["datetime"]).total_seconds() / 3600 - 3
            if hours_since_end <= 0:
                skipped += 1
                continue
            parsed = parse_match(fotmob.match_details_raw(x["fm_id"], max_age_h=hours_since_end) or {}, div, league, season)
            if parsed is None:
                skipped += 1
                continue
            match, rows = parsed
            for side, name in (("h", match["home"]), ("a", match["away"])):
                club = club_title(name, titles)
                assign_ids([r for r in rows if r["side"] == side], rosters.get(club, {}), known)
            new_m.append(match); new_p.extend(rows)
    if new_m:
        add_m = pd.DataFrame(new_m)[MATCH_COLS]
        add_p = pd.DataFrame(new_p)
        assert_no_market_columns(add_m, "fotmob xg matches"); assert_no_market_columns(add_p, "fotmob xg players")
        matches = pd.concat([matches, add_m], ignore_index=True)
        players = pd.concat([players, add_p[players.columns]], ignore_index=True)
        ID_MAP.write_text(json.dumps(known, sort_keys=True))
    mapped = sum(1 for r in new_p if not str(r["player_id"]).startswith("fm"))
    print(f"fotmob xg fill: {len(new_m)} matches added, {len(new_p)} player rows ({mapped} mapped to existing players), {skipped} skipped or deferred")
    return matches, players
