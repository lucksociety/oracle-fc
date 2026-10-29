"""End-to-end research run: tune -> walk-forward -> nested ensemble -> evaluate
-> champion/challenger decision -> write docs/BACKTEST.md + registry."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from . import __version__, config, metrics, store
from .backtest import default_models, evaluate, nested_ensemble, season_of, tune, walk_forward
from .experiments import load_registry, log_experiment, save_registry
from .models.ensemble import fit_weights

VALID_START, TEST_START = "2021-07-01", "2023-07-01"
COMPONENTS = ["dynamic_dc", "elo", "standard_dc", "home_away_rate"]


def main(skip_tune: bool = False):
    df = store.load()
    cutoff = df["date"].max()
    print(f"data rows={len(df)} cutoff={cutoff.date()}")
    if skip_tune:
        params = {"half_life_days": 240.0, "kappa": 8.0, "elo_k": 22.0}
        tune_log = []
    else:
        params, tune_log = tune(df, VALID_START, pd.Timestamp(TEST_START) - pd.Timedelta(days=1))
    log_experiment("hyperparameter_search", {"window": [VALID_START, TEST_START], "selected": params,
                                             "grid": tune_log})
    print("selected params", params)
    models = default_models(params)
    wf = walk_forward(df, VALID_START, str((cutoff + pd.Timedelta(days=1)).date()), models)
    test_seasons = sorted({season_of(d) for d in wf.fx["date"] if d >= pd.Timestamp(TEST_START)})
    ens, weights = nested_ensemble(wf, COMPONENTS, test_seasons)
    test_mask = (wf.fx["date"] >= pd.Timestamp(TEST_START)).to_numpy()
    res, pms, fx = evaluate(wf, test_mask, {"ensemble": ens}, champion="ensemble")
    res["ensemble_weights_by_season"] = weights
    res["params"] = params
    res["data_cutoff"] = str(cutoff.date())
    res["validation_window"] = [VALID_START, TEST_START]
    res["test_window"] = [TEST_START, str(cutoff.date())]

    # production ensemble weights: all OOS predictions up to the cutoff
    ok = np.all([np.isfinite(wf.mats[c][:, 0, 0]) for c in COMPONENTS], axis=0)
    w_prod = fit_weights([wf.mats[c][ok] for c in COMPONENTS], wf.fx["hg"].to_numpy()[ok],
                         wf.fx["ag"].to_numpy()[ok])
    prod_weights = dict(zip(COMPONENTS, [round(float(x), 4) for x in w_prod]))

    # champion / challenger decision (predefined rule)
    bs = res["bootstrap_vs_champion"]["dynamic_dc"]
    ens_better = all(bs[k]["ci95"][1] < 0 for k in ("rps", "exact_log_score"))
    champion = "ensemble" if ens_better else "dynamic_dc"
    res["promotion_rule"] = ("Challenger (ensemble) replaces frozen baseline (dynamic_dc) only if the 95% "
                             "block-bootstrap CI of the RPS and exact-score log-score differences are both < 0.")
    res["champion"] = champion

    # per-division confidence table for reports (champion)
    pm = pms[champion]
    divs = fx["div"].to_numpy()
    conf = {"overall": metrics.favourite_calibration(pm), "by_division": {}}
    for d in sorted(set(divs)):
        sel = divs == d
        if sel.sum() >= 150:
            sub = {k: v[sel] for k, v in pm.items()}
            conf["by_division"][d] = {"summary": metrics.summary(sub)}
    conf["overall_summary"] = res["models"][champion]
    conf["baseline_summary"] = res["models"]["home_away_rate"]

    version = f"{__version__}+{champion}-hl{int(params['half_life_days'])}-k{params['kappa']:g}-elo{params['elo_k']:g}"
    reg = {"champion": {"name": champion, "version": version, "params": params,
                        "ensemble_weights": prod_weights, "components": COMPONENTS,
                        "data_cutoff": str(cutoff.date())},
           "challenger": {"name": "ensemble" if champion != "ensemble" else "dynamic_dc"},
           "confidence": conf}
    # keep the layers validated by the later weekly steps (context backtest, calibration); they are
    # re-validated (and replaced or removed) when those steps run right after this one
    prev = (load_registry().get("champion") or {})
    for k in ("context", "calibration"):
        if k in prev:
            reg["champion"][k] = prev[k]
    save_registry(reg)
    config.BACKTEST_DIR.mkdir(parents=True, exist_ok=True)
    (config.BACKTEST_DIR / "latest_summary.json").write_text(json.dumps(res, indent=1, default=float))
    rec = log_experiment("walk_forward_backtest", {
        "test_window": res["test_window"], "n": res["n_matches"], "champion": champion, "version": version,
        "metrics": {k: res["models"][k] for k in res["models"]}, "weights": weights,
        "prod_weights": prod_weights})
    write_markdown(res, prod_weights, rec["id"])
    print(json.dumps({k: {m: round(v[m], 4) for m in ("rps", "log_loss", "exact_log_score", "top3", "top5")}
                      for k, v in res["models"].items()}, indent=1))
    print("champion", champion)


def _fmt(x, d=4):
    return f"{x:.{d}f}" if isinstance(x, float) else str(x)


def write_markdown(res, prod_weights, exp_id):
    L = []
    L.append("# ORACLE FC — Walk-forward backtest (genuine out-of-sample)\n")
    L.append(f"*Generated by `python -m oraclefc.cli backtest` — experiment id `{exp_id}`. "
             "Every number below comes from that run; nothing is hand-edited.*\n")
    L.append(f"- Data cutoff: **{res['data_cutoff']}**")
    L.append(f"- Hyper-parameter / validation window: {res['validation_window'][0]} → {res['validation_window'][1]} (not scored below)")
    L.append(f"- Test window: **{res['test_window'][0]} → {res['test_window'][1]}**, weekly refits, fit uses only matches dated before each refit date")
    L.append(f"- Matches scored (all models rated): **{res['n_matches']:,}** (excluded because a team had no prior data for some model: {res['n_excluded_unrated']:,})")
    L.append(f"- Selected hyper-parameters: `{res['params']}`")
    L.append("- No odds, prices or third-party forecasts are used anywhere in training, tuning, ensembling or evaluation.\n")
    L.append("## Headline metrics (lower is better except top-k hit rates)\n")
    L.append("| Model | RPS | 1X2 log loss | Brier | Exact-score log score | Top-1 | Top-3 | Top-5 | Goal MAE | Total-goals MAE |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    order = ["league_avg", "home_away_rate", "standard_poisson", "standard_dc", "elo", "dynamic_dc", "ensemble"]
    for n in order:
        m = res["models"][n]
        L.append(f"| {n} | {m['rps']:.4f} | {m['log_loss']:.4f} | {m['brier']:.4f} | {m['exact_log_score']:.4f} | "
                 f"{m['top1']:.3f} | {m['top3']:.3f} | {m['top5']:.3f} | {m['mae_goals']:.3f} | {m['mae_total']:.3f} |")
    L.append("\n## Ensemble vs each model — block bootstrap (blocks = refit weeks, 2,000 resamples)\n")
    L.append("Difference = ensemble − model (negative = ensemble better). 95% CI.\n")
    L.append("| vs | ΔRPS | 95% CI | Δlog loss | 95% CI | Δexact log score | 95% CI |")
    L.append("|---|---|---|---|---|---|---|")
    for n, b in res["bootstrap_vs_champion"].items():
        L.append(f"| {n} | {b['rps']['mean_diff']:+.5f} | [{b['rps']['ci95'][0]:+.5f}, {b['rps']['ci95'][1]:+.5f}] | "
                 f"{b['log_loss']['mean_diff']:+.5f} | [{b['log_loss']['ci95'][0]:+.5f}, {b['log_loss']['ci95'][1]:+.5f}] | "
                 f"{b['exact_log_score']['mean_diff']:+.5f} | [{b['exact_log_score']['ci95'][0]:+.5f}, {b['exact_log_score']['ci95'][1]:+.5f}] |")
    L.append(f"\n**Promotion rule:** {res['promotion_rule']}  ")
    L.append(f"**Champion after this run: `{res['champion']}`**\n")
    L.append("Nested ensemble weights (each season's weights fitted only on earlier out-of-sample predictions):\n")
    for s, w in res["ensemble_weights_by_season"].items():
        L.append(f"- {s}: `{w}`")
    L.append(f"- production (all OOS predictions to cutoff): `{prod_weights}`\n")
    L.append("## By season (champion vs baselines)\n")
    L.append("| Season | Model | n | RPS | log loss | exact log score | top-5 |")
    L.append("|---|---|---|---|---|---|---|")
    for s, d in res["by_season"].items():
        for n, m in d.items():
            L.append(f"| {s} | {n} | {m['n']} | {m['rps']:.4f} | {m['log_loss']:.4f} | {m['exact_log_score']:.4f} | {m['top5']:.3f} |")
    L.append("\n## Calibration (champion, all three outcome probabilities pooled)\n")
    L.append("| Predicted bin | n | Mean predicted | Observed |")
    L.append("|---|---|---|---|")
    for r in res["calibration"]:
        L.append(f"| {r['bin']} | {r['n']} | {r['mean_pred']:.3f} | {r['observed']:.3f} |")
    L.append("\n### Favourite hit-rate by predicted probability (used for MODEL CONFIDENCE in reports)\n")
    L.append("| P(favourite) | n | mean predicted | hit rate | ± s.e. |")
    L.append("|---|---|---|---|---|")
    for r in res["favourite_calibration"]:
        L.append(f"| {r['lo']:.2f}–{r['hi']:.2f} | {r['n']} | {r['mean_pred']:.3f} | {r['hit_rate']:.3f} | {r['se']:.3f} |")
    L.append("\n## By division (champion vs home/away-rate baseline, RPS)\n")
    L.append("| Div | n | champion RPS | baseline RPS | champion exact LS | baseline exact LS |")
    L.append("|---|---|---|---|---|---|")
    ch = res["champion"]
    for d, v in sorted(res["by_division"].items(), key=lambda kv: kv[1][ch]["rps"]):
        L.append(f"| {d} | {v[ch]['n']} | {v[ch]['rps']:.4f} | {v['home_away_rate']['rps']:.4f} | "
                 f"{v[ch]['exact_log_score']:.4f} | {v['home_away_rate']['exact_log_score']:.4f} |")
    L.append("\n## Weakness analysis (Task 6): systematic bias vs randomness\n")
    L.append("z = (observed − predicted) / s.e.; flagged as *systematic* only when |z| > 3.5 "
             "(≈ Bonferroni for ~120 simultaneous tests). Everything else is consistent with noise.\n")
    L.append("| Div | n | total goals pred/obs (z) | draw rate pred/obs (z) | home win pred/obs (z) | systematic |")
    L.append("|---|---|---|---|---|---|")
    for r in res["weaknesses"]["by_division"]:
        f = lambda k: f"{r[k]['pred']:.3f}/{r[k]['obs']:.3f} ({r[k]['z']:+.1f})"
        L.append(f"| {r['div']} | {r['n']} | {f('total_goals')} | {f('draw_rate')} | {f('home_win_rate')} | "
                 f"{', '.join(r['systematic']) or '—'} |")
    fav = res["weaknesses"]["favourites"]
    if fav["strong_favourite_n"]:
        L.append(f"\nStrong favourites (P ≥ 0.60): n={fav['strong_favourite_n']}, mean predicted "
                 f"{fav['strong_favourite_pred']:.3f}, observed {fav['strong_favourite_obs']:.3f}.")
    (config.ROOT / "docs" / "BACKTEST.md").write_text("\n".join(L) + "\n")


if __name__ == "__main__":
    import sys
    main(skip_tune="--skip-tune" in sys.argv)
