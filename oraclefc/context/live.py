"""Live (pre-match) context for one fixture, using exactly the feature definitions the
backtest validated (context/spec.py), plus clearly flagged display-only information.

Sources (all free, no key): FotMob (lineups — projected or confirmed —, unavailable
players, stadium coordinates), FPL (EPL injury/suspension flags with timestamps),
Open-Meteo (venue weather forecast), Understat history (player xG/xA ratings and
minutes shares, via the PlayerBook built by context.history), our own results data
(rest days / congestion, same definition as the backtest), FotMob venue table (travel).

Every external payload is allow-list parsed and checked by assert_no_market_keys.
"""
from __future__ import annotations

import math
import re
import unicodedata
from difflib import SequenceMatcher

import numpy as np
import pandas as pd

from .. import config
from ..governance import assert_no_market_keys, now_utc_iso
from ..ingest import fotmob, fpl
from ..ingest.http import get_json
from . import history as H
from . import spec
from .tilt import tilt

OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
TOP5 = {"E0", "SP1", "D1", "I1", "F1"}
N_CONFIGS = 200
# ---- unvalidated priors (no point-in-time history exists to fit them) — flagged in every report
PRIORS = {
    "projected_start_prob": 0.85,      # P(a FotMob-projected starter actually starts)
    "inferred_start_prob": 0.70,       # P(a minutes-share-inferred starter starts) when no XI is published
    "doubtful_cap": "FPL chance_of_playing/100 (EPL) or 0.5 for FotMob 'Doubtful'",
}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z ]", " ", s).split())


def name_match(name: str, candidates: dict) -> str | None:
    """candidates: pid -> name. Exact normalised, then surname+initial, then fuzzy >= 0.84."""
    n = _norm(name)
    if not n:
        return None
    norm = {p: _norm(c) for p, c in candidates.items()}
    for p, c in norm.items():
        if c == n:
            return p
    toks = n.split()
    for p, c in norm.items():
        ct = c.split()
        if ct and toks and ct[-1] == toks[-1] and ct[0][0] == toks[0][0]:
            return p
    for p, c in norm.items():  # "Amad Diallo" vs "Amad Diallo Traore"
        ct = set(c.split())
        if len(toks) >= 2 and len(ct) >= 2 and (set(toks) <= ct or ct <= set(toks)):
            return p
    best, bs = None, 0.0
    for p, c in norm.items():
        r = SequenceMatcher(None, n, c).ratio()
        if r > bs:
            best, bs = p, r
    if bs >= 0.84:
        return best
    # single-name players ("Rodri", "Vitinha") / surname-only
    for p, c in norm.items():
        if len(toks) == 1 and toks[0] in c.split():
            return p
    return None


# ------------------------------------------------------------------ fixture -> FotMob match
def find_fotmob_match(home_key: str, away_key: str, home_name: str, away_name: str, kickoff_utc: str | None):
    ven = H.venues()
    ids = {k: int(ven.loc[k, "fm_team_id"]) for k in (home_key, away_key) if k in ven.index}
    ko = pd.Timestamp(kickoff_utc) if kickoff_utc else None
    days = [ko.strftime("%Y-%m-%d")] if ko is not None else []
    if ko is not None:
        days += [(ko - pd.Timedelta(days=1)).strftime("%Y-%m-%d"), (ko + pd.Timedelta(days=1)).strftime("%Y-%m-%d")]
    for d in days:
        rows = fotmob.day_fixtures(d)
        for r in rows:
            if ids.get(home_key) == r["home_id"] and ids.get(away_key) == r["away_id"]:
                return r
        for r in rows:  # name fallback (both names must match)
            if _norm(r["home"]) in (_norm(home_name),) and _norm(r["away"]) == _norm(away_name):
                return r
        for r in rows:  # one id + kickoff within 30 min
            if (ids.get(home_key) == r["home_id"] or ids.get(away_key) == r["away_id"]) and r.get("utc"):
                if abs((pd.Timestamp(r["utc"]) - ko).total_seconds()) <= 1800:
                    return r
    return None


# ------------------------------------------------------------------ weather (Open-Meteo forecast)
def weather_forecast(lat: float, lon: float, kickoff_utc: str) -> dict | None:
    ko = pd.Timestamp(kickoff_utc).tz_convert("UTC") if pd.Timestamp(kickoff_utc).tzinfo else pd.Timestamp(kickoff_utc)
    if (ko.tz_localize(None) if ko.tzinfo else ko) - pd.Timestamp.utcnow().tz_localize(None) > pd.Timedelta(days=15):
        return None
    d = get_json(OPEN_METEO, config.RAW_DIR / "weather_live" / f"{lat:.3f}_{lon:.3f}.json", max_age_h=1.0, params={
        "latitude": round(lat, 3), "longitude": round(lon, 3), "hourly": "temperature_2m,precipitation,wind_speed_10m",
        "wind_speed_unit": "ms", "timezone": "UTC", "forecast_days": 16})
    if not d or "hourly" not in d:
        return None
    h = pd.DataFrame(d["hourly"])
    h["time"] = pd.to_datetime(h["time"])
    t0 = (ko.tz_localize(None) if ko.tzinfo else ko).floor("h")
    win = h[(h["time"] >= t0) & (h["time"] <= t0 + pd.Timedelta(hours=1))]
    if win.empty:
        return None
    out = {"precip_mm_2h": float(win["precipitation"].sum()), "wind_ms": float(win["wind_speed_10m"].mean()),
           "temp_c": float(win["temperature_2m"].iloc[0]), "source": "Open-Meteo forecast (hourly, UTC)",
           "source_url": f"{OPEN_METEO}?latitude={round(lat, 3)}&longitude={round(lon, 3)}",
           "fetched_at": now_utc_iso(), "lat": lat, "lon": lon}
    assert_no_market_keys(out, "weather")
    return out


# ------------------------------------------------------------------ rest (same definition as backtest)
def rest_features(df: pd.DataFrame, key: str, date: pd.Timestamp) -> dict:
    d = df.loc[(df["home_key"] == key) | (df["away_key"] == key), "date"]
    d = d[d < date].sort_values()
    if d.empty:
        return {"rest_days": None, "n21": None}
    return {"rest_days": int((date - d.iloc[-1]).days), "n21": int(((d >= date - pd.Timedelta(days=21))).sum()),
            "last_match": str(d.iloc[-1].date())}


# ------------------------------------------------------------------ lineup configurations
class LineupModel:
    def __init__(self, book):
        self.book = book

    def team_candidates(self, team, now):
        b = self.book
        rows = []
        for p in b.team_players.get(team, ()):
            s = b.minutes_share(team, p, now)
            if np.isfinite(s) and s > 0.02:
                rows.append((p, b.pos.get(p, "M"), float(s)))
        return sorted(rows, key=lambda r: -r[2])

    def baseline(self, team):
        ha, hc = self.book.hist_att.get(team, []), self.book.hist_cont.get(team, [])
        if len(ha) < H.BASELINE_N:
            return None
        return float(np.mean(ha[-H.BASELINE_N:])), float(np.mean(hc[-H.BASELINE_N:]))

    def features(self, team, starters, now):
        base = self.baseline(team)
        if base is None:
            return None
        att, cont, gk = H.xi_indices(self.book, team, starters, now)
        return (float(np.clip(np.log(att / base[0]), -0.6, 0.6)), float(np.clip(cont - base[1], -4, 2)), gk)

    def configurations(self, team, xi, unavailable_pids: set, start_prob: dict, now, rng, k=N_CONFIGS):
        """xi: [(pid, group)] expected starters. Each starter starts with start_prob[pid];
        otherwise the slot is filled by an available same-group squad player drawn in
        proportion to recent minutes share. Returns list of (A, C, G)."""
        cands = [c for c in self.team_candidates(team, now) if c[0] not in unavailable_pids]
        out = []
        xi_ids = {p for p, _ in xi}
        for _ in range(k):
            cfg, used = [], set(xi_ids)
            for p, g in xi:
                if rng.random() < start_prob.get(p, 1.0):
                    cfg.append((p, g))
                    continue
                pool = [c for c in cands if c[1] == g and c[0] not in used]
                if not pool:
                    cfg.append((p, g))
                    continue
                w = np.array([c[2] for c in pool])
                c = pool[rng.choice(len(pool), p=w / w.sum())]
                used.add(c[0])
                cfg.append((c[0], g))
            f = self.features(team, cfg, now)
            if f is not None:
                out.append(f)
        return out

    def inferred_xi(self, team, unavailable_pids, now):
        cands = [c for c in self.team_candidates(team, now) if c[0] not in unavailable_pids]
        gks = [c for c in cands if c[1] == "G"][:1]
        outf = [c for c in cands if c[1] != "G"][:10]
        return [(p, g) for p, g, _ in gks + outf]


# ------------------------------------------------------------------ main entry point
def build(engine, r, fixture: dict, base_matrix: np.ndarray, kept: dict, shadow: dict | None = None):
    """Return the context block for one resolved fixture: raw information, features,
    the per-family log-rate deltas, the adjusted matrix and per-factor shifts.
    ``kept``: {family: coefficient list} for families that passed validation."""
    ctx = {"fetched_at": now_utc_iso(), "families_applied": [], "flags": [], "sources": []}
    ko = fixture.get("kickoff_utc")
    date = pd.Timestamp(ko).tz_convert("UTC").tz_localize(None).normalize() if ko else engine.as_of
    now = date
    # ---------- FotMob match
    fm = None
    try:
        row = find_fotmob_match(r.home_key, r.away_key, r.home, r.away, ko)
        fm = fotmob.match_context(row["fm_match_id"]) if row else None
    except Exception as e:  # network / parse problems must never block a forecast
        ctx["flags"].append(f"FotMob unavailable: {type(e).__name__}")
    if fm:
        ctx["sources"].append({"name": "FotMob match page", "url": fm["source_url"], "fetched_at": fm["fetched_at"]})
    else:
        ctx["flags"].append("No FotMob match found for this fixture: lineups/injuries not available.")
    # ---------- FPL (EPL only)
    fpl_rows = []
    if r.div == "E0":
        try:
            fpl_rows = fpl.availability()
            ctx["sources"].append({"name": "Fantasy Premier League availability", "url": fpl.URL,
                                   "fetched_at": now_utc_iso()})
        except Exception:
            ctx["flags"].append("FPL availability feed unavailable.")
    # ---------- lineups & absences
    lm = LineupModel(engine.player_book) if getattr(engine, "player_book", None) is not None else None
    rng = np.random.default_rng(20261028)
    lineups, feats, absences = {}, {}, {}
    for side, key, nm in (("home", r.home_key, r.home), ("away", r.away_key, r.away)):
        t = (fm or {}).get("teams", {}).get(side, {}) if fm else {}
        status = (fm or {}).get("lineup_status", "none")
        book_names = {p: lm.book.name.get(p, "") for p in lm.book.team_players.get(key, ())} if lm else {}
        # absences: FotMob + FPL (EPL)
        ab = []
        for u in t.get("unavailable", []) if t else []:
            ab.append({"player": u["name"], "type": u.get("type"), "expected_return": u.get("expected_return"),
                       "source": "FotMob", "source_url": fm["source_url"], "fetched_at": fm["fetched_at"]})
        fpl_team = [x for x in fpl_rows if x["team"] and _team_like(x["team"], nm)]
        for x in fpl_team:
            if x["status"] == "unavailable" and re.search(r"joined|loan|permanent", x.get("news") or "", re.I):
                continue  # departed players, not absences
            full = f"{x['first_name']} {x['second_name']}".strip()
            j = name_match(full, {i: a["player"] for i, a in enumerate(ab)}) if ab else None
            if j is None:
                j = name_match(x["name"], {i: a["player"] for i, a in enumerate(ab)}) if ab else None
            if j is not None and ab[j]["source"] == "FotMob":
                ab[j].update({"source": "FotMob + FPL", "chance_of_playing": x["chance_of_playing"],
                              "fpl_status": x["status"], "fpl_news": x["news"], "fpl_news_added": x["news_added"]})
                continue
            ab.append({"player": f"{x['first_name']} {x['second_name']}".strip(), "type": x["status"],
                       "expected_return": x["news"], "chance_of_playing": x["chance_of_playing"],
                       "source": "FPL", "source_url": fpl.URL, "fetched_at": x["news_added"]})
        absences[side] = ab
        unavailable_pids, start_prob = set(), {}
        for a in ab:
            pid = name_match(a["player"], book_names) if book_names else None
            if pid is None:
                continue
            cop = a.get("chance_of_playing")
            doubtful = str(a.get("expected_return") or "").lower() == "doubtful" or a.get("type") == "doubtful"
            if cop is not None and cop > 0:
                start_prob[pid] = cop / 100.0
            elif cop == 0 or not doubtful:
                unavailable_pids.add(pid)
            else:
                start_prob[pid] = 0.5
        xi_named = [{"name": p["name"], "pos": p["pos"]} for p in t.get("starters", [])] if t else []
        mode = {"confirmed": "confirmed", "projected": "projected"}.get(status, "none") if xi_named else "none"
        info = {"status": mode, "source": (fm or {}).get("lineup_source") if xi_named else None,
                "formation": t.get("formation") if t else None, "starters": xi_named,
                "fetched_at": (fm or {}).get("fetched_at")}
        if lm is not None and r.div in TOP5 and key in lm.book.team_players:
            xi, unmatched = [], []
            for p in xi_named:
                pid = name_match(p["name"], book_names)
                g = p["pos"] or (lm.book.pos.get(pid) if pid else None) or "M"
                if pid is None:
                    unmatched.append(p["name"])
                    pid = f"fotmob:{p['name']}"
                xi.append((pid, g))
            if mode == "none":
                xi = lm.inferred_xi(key, unavailable_pids, now)
                info["status"] = "inferred"
                info["starters"] = [{"name": lm.book.name.get(p, p), "pos": g} for p, g in xi]
                sp = PRIORS["inferred_start_prob"]
            else:
                sp = 1.0 if mode == "confirmed" else PRIORS["projected_start_prob"]
            probs = {p: min(sp, start_prob.get(p, 1.0)) for p, _ in xi}
            k = 1 if (mode == "confirmed") else N_CONFIGS
            cfgs = lm.configurations(key, xi, unavailable_pids, probs, now, rng, k=k)
            info["n_configurations"] = len(cfgs)
            info["unmatched_players"] = unmatched
            if cfgs:
                feats[side] = np.array(cfgs)
                info["mean_xi_attack_index"] = round(float(np.mean([c[0] for c in cfgs])), 3)
                info["mean_continuity"] = round(float(np.mean([c[1] for c in cfgs])), 3)
                info["p_backup_gk"] = round(float(np.mean([c[2] for c in cfgs])), 3)
        elif r.div not in TOP5:
            info["note"] = ("No point-in-time player-rating history for this league (Understat covers the top-5 "
                            "leagues only): lineup shown for information, NOT applied.")
        lineups[side] = info
    ctx["lineups"], ctx["absences"] = lineups, absences

    # ---------- rest / travel / weather (raw)
    rh, ra = rest_features(engine.df, r.home_key, date), rest_features(engine.df, r.away_key, date)
    ctx["rest"] = {"home": rh, "away": ra, "definition": "days since previous league/UCL match in ORACLE data"}
    ven = H.venues()
    km = None
    if not fixture.get("neutral") and r.home_key in ven.index and r.away_key in ven.index:
        a, b = ven.loc[r.home_key], ven.loc[r.away_key]
        km = float(H.haversine_km(a["lat"], a["lon"], b["lat"], b["lon"]))
    ctx["travel"] = {"away_travel_km": None if km is None else round(km, 1)}
    lat = lon = None
    if fm and fm["venue"].get("lat") is not None:
        lat, lon = float(fm["venue"]["lat"]), float(fm["venue"]["lon"])
        ctx["venue"] = fm["venue"]
    elif r.home_key in ven.index:
        lat, lon = float(ven.loc[r.home_key, "lat"]), float(ven.loc[r.home_key, "lon"])
        ctx["venue"] = {"name": ven.loc[r.home_key, "venue"], "city": ven.loc[r.home_key, "city"], "lat": lat, "lon": lon}
    wx = None
    if lat is not None and ko:
        try:
            wx = weather_forecast(lat, lon, ko)
        except Exception:
            wx = None
    ctx["weather"] = wx
    if wx is None:
        ctx["flags"].append("Weather: no forecast yet (Open-Meteo covers the next 16 days) or venue unknown.")

    # ---------- family deltas (only validated families move the numbers)
    f1 = {"rest_h": [rh["rest_days"] if rh["rest_days"] is not None else np.nan],
          "rest_a": [ra["rest_days"] if ra["rest_days"] is not None else np.nan],
          "n21_h": [rh["n21"] if rh["n21"] is not None else np.nan], "n21_a": [ra["n21"] if ra["n21"] is not None else np.nan],
          "travel_km": [km if km is not None else np.nan], "neutral": [float(bool(fixture.get("neutral")))],
          "precip_mm_2h": [wx["precip_mm_2h"] if wx else np.nan], "wind_ms": [wx["wind_ms"] if wx else np.nan],
          "temp_c": [wx["temp_c"] if wx else np.nan]}
    base = np.asarray(base_matrix, float)

    def family(fam, beta):
        """-> (matrix, dh array, da array) or None when the family has no live features."""
        if fam == "lineup":
            if not feats:
                return None
            nh = feats.get("home", np.zeros((1, 3)))
            na = feats.get("away", np.zeros((1, 3)))
            n = max(len(nh), len(na))
            ih = rng.integers(len(nh), size=n) if len(nh) < n else np.arange(n)
            ia = rng.integers(len(na), size=n) if len(na) < n else np.arange(n)
            fl = {"A_h": nh[ih, 0], "C_h": nh[ih, 1], "G_h": nh[ih, 2], "A_a": na[ia, 0], "C_a": na[ia, 1], "G_a": na[ia, 2]}
            dh, da = spec.deltas("lineup", fl, beta)
            return tilt(np.broadcast_to(base, (n,) + base.shape), dh, da).mean(0), dh, da
        dh, da = spec.deltas(fam, f1, beta)
        return tilt(base, float(dh[0]), float(da[0])), dh, da

    dh_tot, da_tot = 0.0, 0.0
    shifts = []
    lineup_mix = None
    for fam, beta in kept.items():
        res = family(fam, beta)
        if res is None:
            shifts.append({"factor": fam, "applied": False, "reason": "no live features for this fixture"})
            continue
        M, dh, da = res
        shifts.append(_shift(fam, base, M, float(np.mean(dh)), float(np.mean(da))))
        if fam == "lineup":
            lineup_mix = (dh, da)
        else:
            dh_tot += float(dh[0])
            da_tot += float(da[0])
    for fam, beta in (shadow or {}).items():
        if fam in kept:
            continue
        res = family(fam, beta)
        if res is None:
            shifts.append({"factor": fam, "applied": False, "reason": "failed validation; no live features"})
            continue
        M, dh, da = res
        sh = _shift(fam, base, M, float(np.mean(dh)), float(np.mean(da)))
        sh.update({"applied": False, "reason": "failed out-of-sample validation: NOT applied (would-be shift shown "
                                               "for transparency)"})
        shifts.append(sh)
    if lineup_mix is not None:
        final = tilt(np.broadcast_to(base, (len(lineup_mix[0]),) + base.shape),
                     lineup_mix[0] + dh_tot, lineup_mix[1] + da_tot).mean(0)
    else:
        final = tilt(base, dh_tot, da_tot)
    ctx["factor_shifts"] = shifts
    mh = float(np.mean(lineup_mix[0])) if lineup_mix is not None else 0.0
    ma = float(np.mean(lineup_mix[1])) if lineup_mix is not None else 0.0
    ctx["total_shift"] = _shift("all context", base, final, dh_tot + mh, da_tot + ma)
    ctx["families_applied"] = [s["factor"] for s in shifts if s.get("applied")]
    ctx["features"] = {k: (None if not np.isfinite(v[0]) else float(v[0])) for k, v in f1.items()
                       if isinstance(v[0], (int, float)) or v[0] is None}
    assert_no_market_keys(ctx, "match context")
    return ctx, final


def _team_like(fpl_team: str, our_name: str) -> bool:
    a, b = _norm(fpl_team).replace("utd", "united"), _norm(our_name).replace("utd", "united")
    return a == b or a in b or b in a or SequenceMatcher(None, a, b).ratio() > 0.8


def _probs(M):
    h = np.tril(M, -1).sum()
    d = np.trace(M)
    a = np.triu(M, 1).sum()
    k = np.arange(M.shape[0])
    return float(h), float(d), float(a), float((M.sum(1) * k).sum()), float((M.sum(0) * k).sum())


def _shift(name, base, M, dh, da):
    b, m = _probs(base), _probs(M)
    return {"factor": name, "applied": True, "home_rate_mult": round(math.exp(dh), 4), "away_rate_mult": round(math.exp(da), 4),
            "d_p_home_pp": round(100 * (m[0] - b[0]), 2), "d_p_draw_pp": round(100 * (m[1] - b[1]), 2),
            "d_p_away_pp": round(100 * (m[2] - b[2]), 2), "d_xg_home": round(m[3] - b[3], 3), "d_xg_away": round(m[4] - b[4], 3)}
