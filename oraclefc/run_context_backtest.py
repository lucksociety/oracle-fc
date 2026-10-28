"""Champion/challenger backtest of every match-context feature family.

Protocol (pre-registered in docs/CONTEXT.md before results were seen):
1. Base = the production ensemble's walk-forward out-of-sample matrices (weekly refits,
   data strictly before each refit date; ensemble weights for season S learned only from
   OOS predictions before S).
2. For each family F (rest, travel, weather, lineup) and each test season S in
   2023/24 .. current, coefficients are fitted on base OOS matches from 2022-07-01 up to
   the start of S (exact-score log likelihood of the tilted matrix, ridge-shrunk to 0) and
   applied to S. Nothing from S is used to fit S.
3. A family is KEPT only if, on the matches where it is available, BOTH the RPS and the
   1X2 log-loss mean differences vs base are < 0 AND the 95% block-bootstrap CI (blocks =
   refit weeks) of at least one of them lies entirely below 0.
4. xG (Understat) is tested as a model component: ensemble with xg_dc vs ensemble without,
   same nested protocol, same rule.
5. Kept families are then fitted jointly and the combined model is evaluated the same way.
"""
from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd

from . import config, metrics, store
from .backtest import nested_ensemble, season_of, walk_forward, WalkForward
from .context import history as H
from .context import spec
from .context.tilt import fit_coefficients, tilt
from .experiments import load_registry, log_experiment, save_registry
from .models.baselines import HomeAwayRate
from .models.dixon_coles import dynamic_dc, standard_dc, xg_dc
from .models.elo import EloGoals

START, FEAT_TRAIN_START, TEST_START = "2021-07-01", "2022-07-01", "2023-07-01"
BASE_COMPONENTS = ["dynamic_dc", "elo", "standard_dc", "home_away_rate"]
CACHE = config.MODEL_DIR / "oos_context_wf.npz"


def features(df: pd.DataFrame, us_map: pd.DataFrame) -> pd.DataFrame:
    t0 = time.time()
    f = df[["match_id", "date", "div", "home_key", "away_key", "neutral", "kickoff"]].copy()
    f = f.merge(H.rest_table(df), on="match_id", how="left")
    ven = H.venues()
    f = f.merge(H.travel_table(df, ven), on="match_id", how="left")
    f["ko_utc"] = H.kickoff_utc(df).to_numpy()
    w = H.weather_table(f)
    f = f.merge(w, on="match_id", how="left")
    lu, _ = H.lineup_history(us_map)
    f = f.merge(lu.drop(columns=["us_id"]).drop_duplicates("match_id"), on="match_id", how="left")
    print(f"features built in {time.time()-t0:.0f}s: rest {f['rest_h'].notna().mean():.1%}, "
          f"travel {f['travel_km'].notna().mean():.1%}, weather {f['temp_c'].notna().mean():.1%}, "
          f"lineup {f['A_h'].notna().mean():.1%}", flush=True)
    return f


def run_wf(df, cutoff, params):
    if CACHE.exists():
        z = np.load(CACHE, allow_pickle=True)
        fx = pd.read_parquet(CACHE.with_suffix(".parquet"))
        if str(z["cutoff"]) == str(cutoff.date()):
            print("using cached walk-forward", flush=True)
            return WalkForward(list(z["names"]), fx, {n: z[n] for n in z["names"]})
    models = [dynamic_dc(params["half_life_days"], params["kappa"]), EloGoals(k=params["elo_k"]),
              standard_dc(), HomeAwayRate(), xg_dc(params["half_life_days"], params["kappa"], 0.5)]
    wf = walk_forward(df, START, str((cutoff + pd.Timedelta(days=1)).date()), models)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(CACHE, names=np.array(wf.names), cutoff=str(cutoff.date()), **wf.mats)
    wf.fx.to_parquet(CACHE.with_suffix(".parquet"))
    return wf


def _pm(M, hg, ag):
    return metrics.per_match(M.astype(float), hg, ag)


def compare(a_pm, b_pm, blocks):
    out = {}
    for k in ("rps", "log_loss", "exact_log_score"):
        out[k] = metrics.block_bootstrap_diff(b_pm[k], a_pm[k], blocks)  # challenger − base
    return out


def keep_rule(c):
    r, l = c["rps"], c["log_loss"]
    return bool(r["mean_diff"] < 0 and l["mean_diff"] < 0 and (r["ci95"][1] < 0 or l["ci95"][1] < 0))


def available(fam, F):
    if fam == "rest":
        return F["rest_h"].notna().to_numpy() & F["rest_a"].notna().to_numpy()
    if fam == "travel":
        return F["travel_km"].notna().to_numpy()
    if fam == "weather":
        return F["temp_c"].notna().to_numpy()
    if fam == "lineup":
        return F["A_h"].notna().to_numpy() & F["A_a"].notna().to_numpy()
    raise KeyError(fam)


def stacked(fams, F):
    Xh, Xa = zip(*[spec.design(f, {c: F[c].to_numpy() for c in F.columns}) for f in fams])
    return np.hstack(Xh), np.hstack(Xa)


def nested_eval(base, F, fams, hg, ag, seasons, dates, avail, test_seasons):
    Xh, Xa = stacked(fams, F)
    out = base.copy()
    coefs = {}
    for s in test_seasons:
        s0 = pd.Timestamp(f"{s[:4]}-07-01")
        tr = avail & (dates >= pd.Timestamp(FEAT_TRAIN_START)) & (dates < s0) & np.isfinite(base[:, 0, 0])
        te = avail & (seasons == s) & np.isfinite(base[:, 0, 0])
        if tr.sum() < 500 or te.sum() == 0:
            continue
        b, se = fit_coefficients(base[tr], hg[tr], ag[tr], Xh[tr], Xa[tr])
        coefs[s] = {"beta": b.round(4).tolist(), "n_train": int(tr.sum())}
        out[te] = tilt(base[te], Xh[te] @ b, Xa[te] @ b)
    return out, coefs


def main():
    df = store.load()
    cutoff = df["date"].max()
    us_map = H.map_understat(df)
    df = H.attach_xg(df, us_map)
    reg = load_registry()
    params = reg.get("champion", {}).get("params") or {"half_life_days": 240.0, "kappa": 8.0, "elo_k": 22.0}
    wf = run_wf(df, cutoff, params)
    fx = wf.fx
    seasons_all = fx["date"].map(season_of)
    eval_seasons = sorted({s for s in seasons_all if s >= "2022/23"})
    base, w_base = nested_ensemble(wf, BASE_COMPONENTS, eval_seasons)
    xgens, w_xg = nested_ensemble(wf, BASE_COMPONENTS + ["xg_dc"], eval_seasons)

    F = fx[["match_id"]].merge(features(df, us_map).drop(columns=["date", "div", "home_key", "away_key", "neutral", "kickoff"]),
                               on="match_id", how="left")
    F["neutral"] = fx["neutral"].astype(float).to_numpy()
    assert len(F) == len(fx)
    hg, ag = fx["hg"].to_numpy(int), fx["ag"].to_numpy(int)
    dates = fx["date"].to_numpy()
    seasons = seasons_all.to_numpy()
    test_seasons = sorted({s for s in seasons if s >= "2023/24"})
    test = (fx["date"] >= pd.Timestamp(TEST_START)).to_numpy() & np.isfinite(base[:, 0, 0])
    blocks = fx["refit_date"].dt.strftime("%Y-%m-%d").to_numpy()

    results = {"data_cutoff": str(cutoff.date()), "test_window": [TEST_START, str(cutoff.date())],
               "feature_train_start": FEAT_TRAIN_START, "families": {}}
    pm_base_all = None

    # ---- xG component
    us_divs = set(H.config.ALL_DIVISIONS) & {"E0", "SP1", "D1", "I1", "F1"}
    m = test & np.isfinite(xgens[:, 0, 0])
    sub = m & fx["div"].isin(us_divs).to_numpy()
    for name, mask in (("xg_component_top5", sub), ("xg_component_all", m)):
        a = _pm(base[mask], hg[mask], ag[mask])
        b = _pm(xgens[mask], hg[mask], ag[mask])
        c = compare(a, b, blocks[mask])
        results["families"][name] = {"n": int(mask.sum()), "base": metrics.summary(a), "challenger": metrics.summary(b),
                                     "delta": c, "kept": keep_rule(c), "weights_by_season": w_xg}
        print(name, int(mask.sum()), {k: round(v["mean_diff"], 5) for k, v in c.items()}, "kept", keep_rule(c), flush=True)
    xg_kept = results["families"]["xg_component_all"]["kept"] and results["families"]["xg_component_top5"]["kept"]
    champion_base = xgens if xg_kept else base

    # ---- context families (each alone, on its available matches)
    kept = []
    prod = {}
    for fam in spec.FAMILIES:
        av = available(fam, F)
        mask = test & av
        out, coefs = nested_eval(champion_base, F, [fam], hg, ag, seasons, dates, av, test_seasons)
        a = _pm(champion_base[mask], hg[mask], ag[mask])
        b = _pm(out[mask], hg[mask], ag[mask])
        c = compare(a, b, blocks[mask])
        k = keep_rule(c)
        results["families"][fam] = {"n": int(mask.sum()), "coverage_of_test": float(mask.sum() / test.sum()),
                                    "params": spec.FAMILIES[fam], "coefs_by_season": coefs,
                                    "base": metrics.summary(a), "challenger": metrics.summary(b), "delta": c, "kept": k}
        print(fam, int(mask.sum()), {kk: (round(v["mean_diff"], 5), [round(x, 5) for x in v["ci95"]]) for kk, v in c.items()},
              "kept", k, coefs, flush=True)
        if k:
            kept.append(fam)

    # ---- combined (kept families jointly; each only where available — unavailable features are 0)
    if kept:
        avs = np.zeros(len(F), bool)
        for f_ in kept:
            avs |= available(f_, F)
        Fz = F.copy()
        out, coefs = nested_eval(champion_base, Fz, kept, hg, ag, seasons, dates, avs, test_seasons)
        a = _pm(champion_base[test], hg[test], ag[test])
        b = _pm(out[test], hg[test], ag[test])
        c = compare(a, b, blocks[test])
        results["combined"] = {"families": kept, "n": int(test.sum()), "base": metrics.summary(a),
                               "challenger": metrics.summary(b), "delta": c, "coefs_by_season": coefs}
        print("combined", kept, {kk: round(v["mean_diff"], 5) for kk, v in c.items()}, flush=True)

    # ---- production coefficients: all OOS rows from FEAT_TRAIN_START (kept + all, for transparency)
    for fam in spec.FAMILIES:
        av = available(fam, F) & (dates >= pd.Timestamp(FEAT_TRAIN_START)) & np.isfinite(champion_base[:, 0, 0])
        Xh, Xa = stacked([fam], F)
        b, se = fit_coefficients(champion_base[av], hg[av], ag[av], Xh[av], Xa[av])
        prod[fam] = {"params": spec.FAMILIES[fam], "beta": b.round(5).tolist(), "se": np.round(se, 5).tolist(),
                     "n": int(av.sum()), "kept": fam in kept}
    if kept:
        av = np.zeros(len(F), bool)
        for f_ in kept:
            av |= available(f_, F)
        av &= (dates >= pd.Timestamp(FEAT_TRAIN_START)) & np.isfinite(champion_base[:, 0, 0])
        Xh, Xa = stacked(kept, F)
        b, se = fit_coefficients(champion_base[av], hg[av], ag[av], Xh[av], Xa[av])
        i = 0
        for f_ in kept:
            k_ = len(spec.FAMILIES[f_])
            prod[f_]["beta_joint"] = b[i:i + k_].round(5).tolist()
            i += k_
    results["production"] = prod
    results["xg_component_kept"] = bool(xg_kept)
    results["kept_families"] = kept

    config.BACKTEST_DIR.mkdir(parents=True, exist_ok=True)
    (config.BACKTEST_DIR / "context_summary.json").write_text(json.dumps(results, indent=1, default=float))
    rec = log_experiment("context_feature_backtest", {
        "kept": kept, "xg_component_kept": xg_kept,
        "deltas": {f: {k: v["delta"][k]["mean_diff"] for k in ("rps", "log_loss", "exact_log_score")}
                   for f, v in results["families"].items()}})
    # registry: context layer of the champion
    reg = load_registry()
    reg.setdefault("champion", {})["context"] = {
        "kept_families": kept, "xg_component": bool(xg_kept),
        "coefficients": {f: prod[f].get("beta_joint", prod[f]["beta"]) for f in kept},
        "unvalidated_priors": PRIORS, "experiment_id": rec["id"], "data_cutoff": str(cutoff.date())}
    if xg_kept:
        reg["champion"]["components"] = BASE_COMPONENTS + ["xg_dc"]
        w_all = nested_weights_prod(wf, BASE_COMPONENTS + ["xg_dc"])
        reg["champion"]["ensemble_weights"] = w_all
    save_registry(reg)
    write_markdown(results, rec["id"])
    return results


# Conservative priors for information with NO point-in-time history (flagged in reports)
PRIORS = {
    "projected_lineup_start_prob": 0.85,
    "inferred_lineup_start_prob": 0.70,
    "doubtful_start_prob": "FPL chance_of_playing/100 (EPL), else 0.5 for 'Doubtful'",
    "non_top5_lineup": "not applied (no player-rating history)",
    "note": ("Projected (unconfirmed) lineups are simulated as 200 XI configurations: each projected starter "
             "starts with p=0.85 (doubtful players: FPL chance of playing, else 0.5), otherwise the slot is filled by "
             "an available same-position squad player drawn in proportion to recent minutes share. Before any XI is "
             "published, the XI is inferred from recent minutes share minus listed absences (p=0.70 per starter). "
             "Outside the Understat top-5 leagues no point-in-time player ratings exist, so lineups are shown but "
             "NOT applied."),
}


def nested_weights_prod(wf, comps):
    from .models.ensemble import fit_weights
    ok = np.all([np.isfinite(wf.mats[c][:, 0, 0]) for c in comps], axis=0)
    w = fit_weights([wf.mats[c][ok] for c in comps], wf.fx["hg"].to_numpy()[ok], wf.fx["ag"].to_numpy()[ok])
    return dict(zip(comps, [round(float(x), 4) for x in w]))


def _f(x, d=5):
    return f"{x:+.{d}f}" if isinstance(x, float) else str(x)


def write_markdown(res, exp_id):
    L = ["# Context-feature backtest (lineups, players, rest, travel, weather, xG)", "",
         f"Experiment `{exp_id}` · data cutoff {res['data_cutoff']} · test window "
         f"{res['test_window'][0]} → {res['test_window'][1]} · feature coefficients trained from "
         f"{res['feature_train_start']} with nested (season-ahead) refits.", "",
         "Differences are **challenger − base** on the matches where the feature exists "
         "(negative = better). 95% CIs: block bootstrap over refit weeks.", "",
         "Keep rule (pre-registered): ΔRPS < 0 **and** Δlog-loss < 0, with at least one 95% CI entirely < 0.", "",
         "| Feature family | Matches | ΔRPS [95% CI] | Δ1X2 log loss [95% CI] | Δexact-score log score | Kept |",
         "|---|---|---|---|---|---|"]
    for f, v in res["families"].items():
        d = v["delta"]
        L.append(f"| {f} | {v['n']:,} | {_f(d['rps']['mean_diff'])} [{_f(d['rps']['ci95'][0])}, {_f(d['rps']['ci95'][1])}] | "
                 f"{_f(d['log_loss']['mean_diff'])} [{_f(d['log_loss']['ci95'][0])}, {_f(d['log_loss']['ci95'][1])}] | "
                 f"{_f(d['exact_log_score']['mean_diff'])} | {'**yes**' if v['kept'] else 'no'} |")
    if res.get("combined"):
        c = res["combined"]
        d = c["delta"]
        L += ["", f"**Combined kept families** ({', '.join(c['families'])}) on all {c['n']:,} test matches: "
              f"ΔRPS {_f(d['rps']['mean_diff'])} [{_f(d['rps']['ci95'][0])}, {_f(d['rps']['ci95'][1])}], "
              f"Δlog loss {_f(d['log_loss']['mean_diff'])} [{_f(d['log_loss']['ci95'][0])}, {_f(d['log_loss']['ci95'][1])}]."]
    L += ["", "## Production coefficients (log expected-goals multipliers per unit of feature)", "",
          "| Family | Parameter | β | s.e. | Kept |", "|---|---|---|---|---|"]
    for f, v in res["production"].items():
        b = v.get("beta_joint", v["beta"])
        for p, bb, s in zip(v["params"], b, v["se"]):
            L.append(f"| {f} | {p} | {bb:+.4f} | {s:.4f} | {'yes' if v['kept'] else 'no (not applied)'} |")
    L += ["", "## Feature definitions", "",
          "* **rest**: short_rest = clip((5 − days since previous match)/3, 0, 1); congestion = clip((matches in previous 21 days − 4)/3, 0, 1). "
          "History contains league + UCL matches only (domestic cups/UEL/UECL missing → rest over-stated in cup weeks).",
          "* **travel**: log(1 + km/100) between the two clubs' home stadiums (FotMob venue coordinates); acts on the home "
          "and away scoring rates separately.",
          "* **weather**: NASA POWER (MERRA-2) hourly reanalysis at the stadium for the two kickoff hours (history); "
          "Open-Meteo forecast for live matches. rain = min(mm,10)/10, wind = clip((m/s − 8)/6, 0, 1.5), "
          "heat = clip((°C − 24)/8, 0, 1.5), cold = clip((2 − °C)/8, 0, 1.5); acts on both teams' scoring.",
          "* **lineup** (Understat top-5 leagues): XI attack = log(Σ starters' shrunk xG+xA per 90 / mean of the team's previous 6 XIs); "
          "continuity = Σ starters' recent minutes share − previous-6 mean; backup GK = starting keeper is not the regular "
          "(regular ≥ 50% recent minutes). Confirmed starting XIs of the match itself are used (published ~60 min before kickoff).",
          "* **xG component**: dynamic Dixon–Coles fitted to 0.5·goals + 0.5·Understat xG, added to the ensemble.",
          "", "Unvalidated (no point-in-time history) — applied conservatively and flagged in every report:", "",
          f"* {PRIORS['note']}",
          "* Injury/suspension lists (FotMob, FPL) are only used to build projected XIs; their effect flows through the "
          "validated lineup coefficients — there is no separate injury coefficient."]
    (config.ROOT / "docs" / "CONTEXT_BACKTEST.md").write_text("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
