"""Phase 7: strict chronological walk-forward backtesting.

At every refit date t (weekly), every model is fitted on matches with
date < t only and forecasts all matches in [t, t+step). Nothing dated on or
after t is visible to the fit. Ensemble weights for each test season are
learned only from out-of-sample predictions made *before* that season starts
(nested walk-forward).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import config, metrics
from .models.baselines import HomeAwayRate, LeagueAverage
from .models.dixon_coles import dynamic_dc, standard_dc, standard_poisson
from .models.elo import EloGoals
from .models.ensemble import combine, fit_weights


def default_models(params: dict | None = None):
    p = params or {}
    return [LeagueAverage(), HomeAwayRate(), standard_poisson(), standard_dc(),
            dynamic_dc(p.get("half_life_days", 240.0), p.get("kappa", 6.0)),
            EloGoals(k=p.get("elo_k", 22.0))]


@dataclass
class WalkForward:
    names: list[str]
    fx: pd.DataFrame            # evaluated matches (with refit date)
    mats: dict[str, np.ndarray]  # model -> (n, 11, 11)


def walk_forward(df: pd.DataFrame, start: str, end: str, models, step_days: int = 7,
                 verbose: bool = True) -> WalkForward:
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    dates = pd.date_range(start, end, freq=f"{step_days}D")
    names = [m.name for m in models]
    out_fx, out_m = [], {n: [] for n in names}
    t0 = time.time()
    for i, t in enumerate(dates):
        fx = df[(df["date"] >= t) & (df["date"] < t + pd.Timedelta(days=step_days)) & (df["date"] <= end)]
        if not len(fx):
            continue
        fx = fx.copy()
        fx["refit_date"] = t
        for m in models:
            m.fit(df, t)
            out_m[m.name].append(m.predict_matrix(fx).astype(np.float32))
        out_fx.append(fx)
        if verbose and i % 20 == 0:
            print(f"  [{i+1}/{len(dates)}] {t.date()} {time.time()-t0:.0f}s", flush=True)
    fx = pd.concat(out_fx, ignore_index=True)
    mats = {n: np.concatenate(v) for n, v in out_m.items()}
    return WalkForward(names, fx, mats)


def season_of(d: pd.Timestamp) -> str:
    y = d.year if d.month >= 7 else d.year - 1
    return f"{y}/{(y + 1) % 100:02d}"


def nested_ensemble(wf: WalkForward, components: list[str], test_seasons: list[str]):
    """Weights for season S fitted only on OOS predictions dated before S starts."""
    fx = wf.fx
    seasons = fx["date"].map(season_of)
    ens = np.full_like(wf.mats[components[0]], np.nan)
    weights = {}
    for s in test_seasons:
        s_start = pd.Timestamp(f"{s[:4]}-07-01")
        tr = (fx["date"] < s_start).to_numpy()
        te = (seasons == s).to_numpy()
        comp_tr = [wf.mats[c][tr] for c in components]
        ok = np.all([np.isfinite(m[:, 0, 0]) for m in comp_tr], axis=0)
        w = fit_weights([m[ok] for m in comp_tr], fx["hg"].to_numpy()[tr][ok], fx["ag"].to_numpy()[tr][ok])
        weights[s] = dict(zip(components, [round(float(x), 4) for x in w]))
        ens[te] = combine([wf.mats[c][te] for c in components], w)
    return ens, weights


def evaluate(wf: WalkForward, mask: np.ndarray, extra: dict[str, np.ndarray] | None = None,
             baseline: str = "home_away_rate", champion: str = "ensemble"):
    mats = dict(wf.mats)
    if extra:
        mats.update(extra)
    common = mask.copy()
    for m in mats.values():
        common &= np.isfinite(m[:, 0, 0])
    fx = wf.fx[common]
    hg, ag = fx["hg"].to_numpy(int), fx["ag"].to_numpy(int)
    pms = {n: metrics.per_match(m[common].astype(float), hg, ag) for n, m in mats.items()}
    res = {"n_matches": int(common.sum()), "n_excluded_unrated": int(mask.sum() - common.sum()),
           "models": {n: metrics.summary(pm) for n, pm in pms.items()}}
    blocks = fx["refit_date"].dt.strftime("%Y-%m-%d").to_numpy()
    res["bootstrap_vs_champion"] = {}
    for n in pms:
        if n == champion:
            continue
        res["bootstrap_vs_champion"][n] = {
            k: metrics.block_bootstrap_diff(pms[champion][k], pms[n][k], blocks)
            for k in ("rps", "log_loss", "exact_log_score")}
    seasons = fx["date"].map(season_of).to_numpy()
    res["by_season"] = {s: {n: metrics.summary({k: v[seasons == s] for k, v in pm.items()})
                            for n, pm in pms.items() if n in (champion, "dynamic_dc", "elo", baseline)}
                        for s in sorted(set(seasons))}
    divs = fx["div"].to_numpy()
    res["by_division"] = {}
    for d in sorted(set(divs)):
        sel = divs == d
        if sel.sum() < 100:
            continue
        res["by_division"][d] = {n: metrics.summary({k: v[sel] for k, v in pm.items()})
                                 for n, pm in pms.items() if n in (champion, baseline)}
    res["calibration"] = metrics.calibration_table(pms[champion])
    res["favourite_calibration"] = metrics.favourite_calibration(pms[champion])
    res["weaknesses"] = weakness_analysis(fx, mats[champion][common].astype(float), pms[champion])
    return res, pms, fx


def weakness_analysis(fx, mats, pm):
    """Systematic-bias checks with z-scores (week-clustered SE is approximated by match SE;
    |z| > 3.5 ≈ Bonferroni threshold for ~40 divisions × 3 tests)."""
    k = np.arange(mats.shape[-1])
    pred_total = (mats.sum(2) * k).sum(1) + (mats.sum(1) * k).sum(1)
    act_total = (fx["hg"] + fx["ag"]).to_numpy(float)
    draw_obs = (fx["hg"] == fx["ag"]).to_numpy(float)
    home_obs = (fx["hg"] > fx["ag"]).to_numpy(float)
    rows = []
    for d, idx in fx.groupby("div").indices.items():
        if len(idx) < 150:
            continue
        r = {"div": d, "n": int(len(idx))}
        for name, pred, obs in (("total_goals", pred_total, act_total), ("draw_rate", pm["p_draw"], draw_obs),
                                ("home_win_rate", pm["p_home"], home_obs)):
            diff = obs[idx] - pred[idx]
            se = diff.std(ddof=1) / np.sqrt(len(idx))
            r[name] = {"pred": float(pred[idx].mean()), "obs": float(obs[idx].mean()),
                       "z": float(diff.mean() / se) if se > 0 else 0.0}
        r["systematic"] = [n for n in ("total_goals", "draw_rate", "home_win_rate") if abs(r[n]["z"]) > 3.5]
        rows.append(r)
    # favourite / underdog
    p = np.stack([pm["p_home"], pm["p_draw"], pm["p_away"]], 1)
    o = pm["outcome"].astype(int)
    strong = p.max(1) >= 0.6
    fav = p.argmax(1)
    fav_rows = {
        "strong_favourite_n": int(strong.sum()),
        "strong_favourite_pred": float(p.max(1)[strong].mean()) if strong.any() else None,
        "strong_favourite_obs": float((fav[strong] == o[strong]).mean()) if strong.any() else None,
    }
    return {"by_division": rows, "favourites": fav_rows}


def tune(df, start, end, grid_hl=(120.0, 240.0, 400.0), grid_kappa=(3.0, 8.0), grid_k=(15.0, 22.0, 30.0)):
    """Hyper-parameter search on the validation window only (14-day refits)."""
    log = []
    best = {}
    best_s = np.inf
    for hl in grid_hl:
        for kap in grid_kappa:
            m = dynamic_dc(hl, kap)
            wf = walk_forward(df, start, end, [m], step_days=14, verbose=False)
            M = wf.mats[m.name]
            ok = np.isfinite(M[:, 0, 0])
            s = metrics.summary(metrics.per_match(M[ok].astype(float), wf.fx["hg"].to_numpy()[ok],
                                                  wf.fx["ag"].to_numpy()[ok]))
            log.append({"model": "dynamic_dc", "half_life_days": hl, "kappa": kap, **s})
            print("   tune dc", hl, kap, round(s["exact_log_score"], 5), round(s["rps"], 5), flush=True)
            if s["exact_log_score"] < best_s:
                best_s, best = s["exact_log_score"], {"half_life_days": hl, "kappa": kap}
    best_e, best_k = np.inf, 22.0
    for k in grid_k:
        m = EloGoals(k=k)
        wf = walk_forward(df, start, end, [m], step_days=14, verbose=False)
        M = wf.mats[m.name]
        ok = np.isfinite(M[:, 0, 0])
        s = metrics.summary(metrics.per_match(M[ok].astype(float), wf.fx["hg"].to_numpy()[ok],
                                              wf.fx["ag"].to_numpy()[ok]))
        log.append({"model": "elo", "k": k, **s})
        print("   tune elo", k, round(s["exact_log_score"], 5), flush=True)
        if s["exact_log_score"] < best_e:
            best_e, best_k = s["exact_log_score"], k
    best["elo_k"] = best_k
    return best, log
