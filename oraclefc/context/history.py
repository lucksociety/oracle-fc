"""Point-in-time historical context features for the backtest.

Every feature for a match dated D uses only information available before kickoff
of that match (results / lineups of earlier matches, the confirmed starting XI of the
match itself — published ~1h before kickoff — fixed venue coordinates and the
weather at the venue at kickoff, which a forecast issued at T-1h would know to
within forecast error).
"""
from __future__ import annotations

import json
from collections import defaultdict

import numpy as np
import pandas as pd

from .. import config
from ..ingest.http import get_json
from ..teams import match_team

METHOD_RANK = {"exact": 0, "alias": 1, "normalised": 2, "core-tokens": 3, "token-subset": 4, "fuzzy": 5}


# ------------------------------------------------------------------ rest & congestion
def rest_table(df: pd.DataFrame) -> pd.DataFrame:
    """Days since each side's previous match and matches in the previous 21 days (all
    competitions present in the data: domestic league + UCL; domestic cups are not in
    the historical data, so rest is over-stated for cup weeks — documented)."""
    long = pd.concat([
        pd.DataFrame({"match_id": df["match_id"], "date": df["date"], "team": df["home_key"], "side": "h"}),
        pd.DataFrame({"match_id": df["match_id"], "date": df["date"], "team": df["away_key"], "side": "a"}),
    ]).sort_values(["team", "date"])
    long["prev"] = long.groupby("team")["date"].shift(1)
    long["rest"] = (long["date"] - long["prev"]).dt.days
    n21 = np.zeros(len(long))
    for _, idx in long.groupby("team").indices.items():
        d = long["date"].to_numpy()[idx].astype("datetime64[D]").astype(np.int64)
        lo = np.searchsorted(d, d - 21, side="left")
        hi = np.searchsorted(d, d, side="left")
        n21[idx] = hi - lo
    long["n21"] = n21
    w = long.pivot_table(index="match_id", columns="side", values=["rest", "n21"], aggfunc="first")
    w.columns = [f"{a}_{b}" for a, b in w.columns]
    return w.reset_index()


# ------------------------------------------------------------------ venues & travel
def venues() -> pd.DataFrame:
    t = pd.read_parquet(config.CONTEXT_DIR / "fotmob_teams.parquet").dropna(subset=["team_key", "lat", "lon"])
    t["rank"] = t["method"].map(METHOD_RANK).fillna(9)
    # a team key claimed by several FotMob ids keeps the most reliable mapping
    best = t.sort_values(["rank"]).groupby("team_key")["fm_team_id"].first()
    t = t[t["fm_team_id"] == t["team_key"].map(best)]
    t = t.sort_values("season").groupby("team_key").tail(1)
    return t.set_index("team_key")[["fm_team_id", "fm_name", "venue", "city", "lat", "lon"]]


def haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = (np.radians(np.asarray(x, float)) for x in (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * np.arcsin(np.sqrt(a))


def travel_table(df: pd.DataFrame, ven: pd.DataFrame) -> pd.DataFrame:
    h = ven.reindex(df["home_key"])
    a = ven.reindex(df["away_key"])
    km = haversine_km(h["lat"].to_numpy(), h["lon"].to_numpy(), a["lat"].to_numpy(), a["lon"].to_numpy())
    return pd.DataFrame({"match_id": df["match_id"].to_numpy(), "travel_km": km,
                         "venue_lat": h["lat"].to_numpy(), "venue_lon": h["lon"].to_numpy()})


# ------------------------------------------------------------------ kickoff times
def kickoff_utc(df: pd.DataFrame) -> pd.Series:
    """Exact UTC kickoff from FotMob fixtures where mapped; else football-data's UK
    kickoff time; else 14:00 UTC (flagged by the caller as approximate)."""
    fx = pd.read_parquet(config.CLEAN_DIR / "fotmob_fixtures.parquet").dropna(subset=["home_key", "away_key", "utc"])
    fx["utc"] = pd.to_datetime(fx["utc"], utc=True).dt.tz_localize(None)
    fx["d"] = fx["utc"].dt.normalize()
    out = pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns]")
    key = fx.set_index(["home_key", "away_key", "d"])["utc"]
    key = key[~key.index.duplicated()]
    for shift in (0, -1, 1):
        miss = out.isna()
        idx = pd.MultiIndex.from_arrays([df.loc[miss, "home_key"], df.loc[miss, "away_key"],
                                         df.loc[miss, "date"] + pd.Timedelta(days=shift)])
        out.loc[miss] = key.reindex(idx).to_numpy()
    miss = out.isna()
    ko = df.loc[miss, "kickoff"].fillna("")
    t = pd.to_datetime(df.loc[miss, "date"].dt.strftime("%Y-%m-%d") + " " + ko.where(ko.str.match(r"^\d\d:\d\d$"), "14:00"))
    uk = t.dt.tz_localize("Europe/London", ambiguous="NaT", nonexistent="NaT").dt.tz_convert("UTC").dt.tz_localize(None)
    out.loc[miss] = uk.to_numpy()
    return out


# ------------------------------------------------------------------ weather (NASA POWER, history)
POWER = "https://power.larc.nasa.gov/api/temporal/hourly/point"


def _cell(lat, lon):
    return round(lat * 2) / 2, round(lon / 0.625) * 0.625  # MERRA-2 grid (0.5° x 0.625°)


def power_cell(lat: float, lon: float, start: str, end: str):
    cache = config.RAW_DIR / "weather_power" / f"{lat:.2f}_{lon:.3f}_{start}_{end}.json"
    d = get_json(POWER, cache, max_age_h=None, timeout=120, params={
        "parameters": "PRECTOTCORR,WS10M,T2M", "community": "RE", "latitude": lat, "longitude": lon,
        "start": start, "end": end, "format": "JSON", "time-standard": "UTC"})
    if not d:
        return None
    p = d["properties"]["parameter"]
    idx = pd.to_datetime(list(p["T2M"].keys()), format="%Y%m%d%H")
    w = pd.DataFrame({k: list(v.values()) for k, v in p.items()}, index=idx).replace(-999.0, np.nan)
    return w


def weather_table(df: pd.DataFrame, start="20220601", end=None, workers: int = 4) -> pd.DataFrame:
    from concurrent.futures import ThreadPoolExecutor

    end = end or (pd.Timestamp.now() - pd.Timedelta(days=5)).strftime("%Y%m%d")
    d = df.dropna(subset=["venue_lat", "venue_lon", "ko_utc"])
    d = d[d["date"] >= pd.Timestamp(start)]
    cells = sorted({_cell(a, b) for a, b in zip(d["venue_lat"], d["venue_lon"])})
    print(f"   weather: {len(d)} matches, {len(cells)} grid cells", flush=True)
    with ThreadPoolExecutor(workers) as ex:
        series = dict(zip(cells, ex.map(lambda c: power_cell(c[0], c[1], start, end), cells)))
    rows = []
    for r in d.itertuples(index=False):
        w = series.get(_cell(r.venue_lat, r.venue_lon))
        if w is None:
            continue
        t0 = pd.Timestamp(r.ko_utc).floor("h")
        win = w.loc[t0: t0 + pd.Timedelta(hours=1)]
        if win.empty or win.isna().all().all():
            continue
        rows.append({"match_id": r.match_id, "precip_mm_2h": float(win["PRECTOTCORR"].sum()),
                     "wind_ms": float(win["WS10M"].mean()), "temp_c": float(win["T2M"].iloc[0])})
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ Understat -> our matches
def map_understat(df: pd.DataFrame) -> pd.DataFrame:
    um = pd.read_parquet(config.CONTEXT_DIR / "understat_matches.parquet")
    um = um[um["is_result"]].copy()
    um["d"] = um["datetime"].dt.normalize()
    out = []
    for div, g in um.groupby("div"):
        sub = df[df["div"] == div]
        names = sorted(set(sub["home"]) | set(sub["away"]))
        country = sub["country"].iloc[0]
        nm = {}
        for n in set(g["home"]) | set(g["away"]):
            m = match_team(n, names)
            nm[n] = f"{country}:{m.canonical}" if m.canonical else None
        g = g.assign(home_key=g["home"].map(nm), away_key=g["away"].map(nm))
        key = sub.set_index(["home_key", "away_key", "date"])["match_id"]
        key = key[~key.index.duplicated()]
        mid = pd.Series(np.nan, index=g.index, dtype=object)
        for s in (0, -1, 1):
            miss = mid.isna()
            idx = pd.MultiIndex.from_arrays([g.loc[miss, "home_key"], g.loc[miss, "away_key"],
                                             g.loc[miss, "d"] + pd.Timedelta(days=s)])
            mid.loc[miss] = key.reindex(idx).to_numpy()
        out.append(g.assign(match_id=mid))
    res = pd.concat(out)
    print(f"   understat->results mapping: {res['match_id'].notna().mean():.1%} of {len(res)} matches")
    return res


def attach_xg(df: pd.DataFrame, us_map: pd.DataFrame | None = None) -> pd.DataFrame:
    """Fill hxg/axg (observed shot-quality, not a prediction) from Understat."""
    us_map = us_map if us_map is not None else map_understat(df)
    x = us_map.dropna(subset=["match_id"]).drop_duplicates("match_id").set_index("match_id")
    df = df.copy()
    df["hxg"] = df["match_id"].map(x["hxg"]).astype(float)
    df["axg"] = df["match_id"].map(x["axg"]).astype(float)
    return df


# ------------------------------------------------------------------ lineup / player features
POS_GROUP = {"GK": "G", "DR": "D", "DC": "D", "DL": "D", "DMR": "M", "DMC": "M", "DML": "M",
             "MR": "M", "MC": "M", "ML": "M", "AMR": "F", "AMC": "F", "AML": "F", "FW": "F"}
RATING_HL, SHARE_HL, PRIOR_90S = 365.0, 45.0, 5.0
BASELINE_N = 6


class PlayerBook:
    """Exponentially-weighted per-player attacking output (xG+xA per 90) and
    team-specific minutes share, updated match by match (point-in-time)."""

    def __init__(self, pos_prior: dict | None = None):
        self.att = defaultdict(lambda: [0.0, 0.0, None])     # pid -> [w*(xg+xa), w*min/90, last_date]
        self.share = defaultdict(lambda: [0.0, None])         # (team, pid) -> [ew minutes/90, last_date]
        self.team_norm = defaultdict(lambda: [0.0, None])     # team -> [ew 1.0 per match, last_date]
        self.pos = {}
        self.name = {}
        self.team_players = defaultdict(set)
        self.pos_prior = pos_prior or {"G": 0.0, "D": 0.08, "M": 0.18, "F": 0.42}

    @staticmethod
    def _decay(val, last, now, hl):
        if last is None:
            return val
        return val * 0.5 ** ((now - last).days / hl)

    def rating(self, pid, now, pos=None):
        s, m, last = self.att[pid] if pid in self.att else (0.0, 0.0, None)
        s, m = self._decay(s, last, now, RATING_HL), self._decay(m, last, now, RATING_HL)
        prior = self.pos_prior.get(pos or self.pos.get(pid, "M"), 0.15)
        return (s + PRIOR_90S * prior) / (m + PRIOR_90S), m

    def minutes_share(self, team, pid, now):
        v, last = self.share[(team, pid)] if (team, pid) in self.share else (0.0, None)
        n, nl = self.team_norm[team] if team in self.team_norm else (0.0, None)
        v, n = self._decay(v, last, now, SHARE_HL), self._decay(n, nl, now, SHARE_HL)
        return v / n if n > 0 else np.nan

    def update(self, team, now, rows):
        n, nl = self.team_norm[team]
        self.team_norm[team] = [self._decay(n, nl, now, SHARE_HL) + 1.0, now]
        for r in rows:
            pid = r["player_id"]
            s, m, last = self.att[pid]
            self.att[pid] = [self._decay(s, last, now, RATING_HL) + (r["xG"] or 0) + (r["xA"] or 0),
                             self._decay(m, last, now, RATING_HL) + (r["time"] or 0) / 90.0, now]
            v, l2 = self.share[(team, pid)]
            self.share[(team, pid)] = [self._decay(v, l2, now, SHARE_HL) + min((r["time"] or 0) / 90.0, 1.0), now]
            self.team_players[team].add(pid)
            if r["position"] in POS_GROUP:
                self.pos[pid] = POS_GROUP[r["position"]]
            self.name[pid] = r["player"]


    def regular_gk(self, team, now):
        best, bs = None, 0.0
        for p in self.team_players.get(team, ()):
            if self.pos.get(p) == "G":
                s = self.minutes_share(team, p, now)
                if np.isfinite(s) and s > bs:
                    best, bs = p, s
        return best, bs


def xi_indices(book: PlayerBook, team, starters: list[tuple[str, str]], now):
    """starters: [(player_id, pos_group)]. Returns (attack_value, continuity, backup_gk)."""
    att = sum(book.rating(p, now, g)[0] for p, g in starters)
    shares = [book.minutes_share(team, p, now) for p, _ in starters]
    cont = float(np.nansum(shares))
    gks = [p for p, g in starters if g == "G"]
    reg, reg_share = book.regular_gk(team, now)
    backup = float(bool(gks) and reg is not None and reg_share >= 0.5 and gks[0] != reg
                   and np.nan_to_num(book.minutes_share(team, gks[0], now)) < 0.5)
    return att, cont, backup


def lineup_history(us_map: pd.DataFrame) -> pd.DataFrame:
    """A = log(XI attacking value / team's recent XI baseline), C = continuity vs baseline,
    G = 1 if the starting GK is not the regular (minutes share < 0.5 while the team had a
    regular keeper). All computed BEFORE the match's own data is added to the book."""
    pl = pd.read_parquet(config.CONTEXT_DIR / "understat_players.parquet")
    pl = pl.merge(us_map[["us_id", "datetime", "match_id", "home_key", "away_key"]], on="us_id", how="inner")
    pl["team"] = np.where(pl["side"] == "h", pl["home_key"], pl["away_key"])
    pl = pl.dropna(subset=["team"]).sort_values(["datetime", "us_id"])
    book = PlayerBook()
    hist_att, hist_cont = defaultdict(list), defaultdict(list)
    rows = []
    for (dt, mid_us), g in pl.groupby(["datetime", "us_id"], sort=True):
        now = pd.Timestamp(dt)
        feats = {"us_id": mid_us, "match_id": g["match_id"].iloc[0]}
        updates = []
        for side, gs in g.groupby("side"):
            team = gs["team"].iloc[0]
            st = gs[gs["position"] != "Sub"]
            starters = [(p, POS_GROUP.get(pos, "M")) for p, pos in zip(st["player_id"], st["position"])]
            att, cont, gk_share = xi_indices(book, team, starters, now)
            ha, hc = hist_att[team], hist_cont[team]
            if len(ha) >= BASELINE_N:
                feats[f"A_{side}"] = float(np.clip(np.log(att / np.mean(ha[-BASELINE_N:])), -0.6, 0.6))
                feats[f"C_{side}"] = float(np.clip(cont - np.mean(hc[-BASELINE_N:]), -4, 2))
                feats[f"G_{side}"] = gk_share
                feats[f"xi_att_{side}"] = att
            ha.append(att)
            hc.append(cont)
            updates.append((team, gs.to_dict("records")))
        for team, recs in updates:
            book.update(team, now, recs)
        rows.append(feats)
    out = pd.DataFrame(rows)
    out = out.dropna(subset=["match_id"])
    book.hist_att, book.hist_cont = hist_att, hist_cont   # live features need the same baselines
    book.last_date = pl["datetime"].max()
    return out, book
