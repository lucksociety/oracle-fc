"""Champion/challenger test of the results-only calibration layer (``oraclefc.calibrate``).

Protocol (fixed before results were seen):
1. Base = production ensemble (registry components) walk-forward OOS matrices, nested
   season-ahead ensemble weights (cached walk-forward of ``run_context_backtest``).
2. For each test season S (2023/24 .. current) every variant is fitted only on base OOS
   matches dated 2022-07-01 .. start of S and applied to S.
3. A variant is eligible only if ΔRPS, Δ1X2 log loss and Δexact-score log score are all < 0 on
   the full test window and the 95% block-bootstrap CIs (blocks = refit weeks) of ΔRPS and
   Δexact-score log score lie entirely below 0 (the ensemble promotion rule).
4. Among eligible variants the one with the lowest exact-score log score is adopted; the
   production layer is refitted on all OOS matches to the cutoff.
No odds, prices or market data are used anywhere (results only).
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from . import __version__, calibrate, config, metrics
from .backtest import WalkForward, nested_ensemble, season_of
from .experiments import load_registry, log_experiment, save_registry
from .run_context_backtest import CACHE, champion_confidence

TRAIN_START, TEST_START = "2022-07-01", "2023-07-01"
VARIANTS = {
    "global": dict(per_div=(), sharpen=False),
    "global+sharpen": dict(per_div=(), sharpen=True),
    "div_goals+sharpen": dict(per_div=("h", "a"), sharpen=True),
    "div_goals_draw+sharpen": dict(per_div=("h", "a", "draw"), sharpen=True),
}


def load_wf() -> WalkForward:
    z = np.load(CACHE, allow_pickle=True)
    fx = pd.read_parquet(CACHE.with_suffix(".parquet"))
    return WalkForward(list(z["names"]), fx, {n: z[n] for n in z["names"]})


def nested_calibrate(base, fx, test_seasons, **kw):
    out = base.copy()
    dates = fx["date"].to_numpy()
    seasons = fx["date"].map(season_of).to_numpy()
    divs = fx["div"].astype(str).to_numpy()
    hg, ag = fx["hg"].to_numpy(int), fx["ag"].to_numpy(int)
    fits = {}
    for s in test_seasons:
        s0 = np.datetime64(pd.Timestamp(f"{s[:4]}-07-01"))
        tr = (dates >= np.datetime64(pd.Timestamp(TRAIN_START))) & (dates < s0) & np.isfinite(base[:, 0, 0])
        te = (seasons == s) & np.isfinite(base[:, 0, 0])
        cal = calibrate.fit(base[tr], hg[tr], ag[tr], divs[tr], **kw)
        out[te] = calibrate.apply(base[te], cal["coef"], divs[te], cal["sharpen"])
        fits[s] = {"n_train": cal["n"], "sharpen": round(cal["sharpen"], 4),
                   "global": {t: round(v, 4) for (t, d), v in cal["coef"].items() if d is None}}
    return out, fits


def market_style_reliability(M, hg, ag, mask):
    """Reliability of the goal-market probabilities the best-bet layer trades (computed from
    the model's own matrices vs results; no prices involved)."""
    G = M.shape[-1]
    k = np.arange(G)
    H, A = np.meshgrid(k, k, indexing="ij")
    defs = {"under_2.5": (H + A) < 2.5, "under_3.5": (H + A) < 3.5, "btts_no": ~((H > 0) & (A > 0)),
            "home_under_1.5": H < 1.5, "away_under_1.5": A < 1.5, "draw": H == A}
    hgm, agm = hg[mask], ag[mask]
    obs = {"under_2.5": hgm + agm < 2.5, "under_3.5": hgm + agm < 3.5, "btts_no": ~((hgm > 0) & (agm > 0)),
           "home_under_1.5": hgm < 1.5, "away_under_1.5": agm < 1.5, "draw": hgm == agm}
    out = {}
    for name, cell in defs.items():
        p = (M[mask] * cell[None]).sum((1, 2))
        o = obs[name].astype(float)
        rows = []
        for lo, hi in ((0.0, 0.3), (0.3, 0.5), (0.5, 0.6), (0.6, 0.7), (0.7, 1.01)):
            m = (p >= lo) & (p < hi)
            if m.sum() >= 100:
                rows.append({"bin": f"{lo:.1f}-{min(hi, 1):.1f}", "n": int(m.sum()), "pred": float(p[m].mean()),
                             "obs": float(o[m].mean()), "se": float(np.sqrt(o[m].mean() * (1 - o[m].mean()) / m.sum()))})
        out[name] = {"mean_pred": float(p.mean()), "mean_obs": float(o.mean()), "bins": rows}
    return out


def main():
    wf = load_wf()
    fx = wf.fx
    reg = load_registry()
    comps = reg["champion"].get("components")
    seasons = sorted({s for s in fx["date"].map(season_of) if s >= "2022/23"})
    test_seasons = [s for s in seasons if s >= "2023/24"]
    base, _ = nested_ensemble(wf, comps, seasons)
    hg, ag = fx["hg"].to_numpy(int), fx["ag"].to_numpy(int)
    test = (fx["date"] >= pd.Timestamp(TEST_START)).to_numpy() & np.isfinite(base[:, 0, 0])
    blocks = fx["refit_date"].dt.strftime("%Y-%m-%d").to_numpy()[test]
    pm_base = metrics.per_match(base[test].astype(float), hg[test], ag[test])
    res = {"n_test": int(test.sum()), "test_window": [TEST_START, str(fx["date"].max().date())],
           "base": metrics.summary(pm_base), "variants": {}}
    print("base", {k: round(v, 5) for k, v in res["base"].items() if k in ("rps", "log_loss", "exact_log_score")})
    mats = {}
    for name, kw in VARIANTS.items():
        M, fits = nested_calibrate(base, fx, test_seasons, **kw)
        mats[name] = M
        pm = metrics.per_match(M[test].astype(float), hg[test], ag[test])
        d = {k: metrics.block_bootstrap_diff(pm[k], pm_base[k], blocks) for k in ("rps", "log_loss", "exact_log_score")}
        ok = (all(d[k]["mean_diff"] < 0 for k in d) and d["rps"]["ci95"][1] < 0 and d["exact_log_score"]["ci95"][1] < 0)
        res["variants"][name] = {"summary": metrics.summary(pm), "delta": d, "eligible": bool(ok), "fits": fits}
        print(name, "eligible" if ok else "-", {k: (round(v["mean_diff"], 5), [round(x, 5) for x in v["ci95"]])
                                                 for k, v in d.items()}, flush=True)
    elig = [n for n, v in res["variants"].items() if v["eligible"]]
    chosen = min(elig, key=lambda n: res["variants"][n]["summary"]["exact_log_score"]) if elig else None
    res["chosen"] = chosen
    res["reliability_base"] = market_style_reliability(base, hg, ag, test)
    if chosen:
        res["reliability_chosen"] = market_style_reliability(mats[chosen], hg, ag, test)
    # weakness check (division totals / draw) before vs after
    from .backtest import weakness_analysis
    res["weakness_base"] = weakness_analysis(fx[test], base[test].astype(float), pm_base)
    if chosen:
        pm_c = metrics.per_match(mats[chosen][test].astype(float), hg[test], ag[test])
        res["weakness_chosen"] = weakness_analysis(fx[test], mats[chosen][test].astype(float), pm_c)
    rec = log_experiment("calibration_layer", {"test_window": res["test_window"], "n": res["n_test"],
                                               "components": comps, "chosen": chosen,
                                               "deltas": {n: {k: v["delta"][k]["mean_diff"] for k in v["delta"]}
                                                          for n, v in res["variants"].items()}})
    res["experiment_id"] = rec["id"]
    if chosen:
        kw = VARIANTS[chosen]
        ok = (fx["date"] >= pd.Timestamp(TRAIN_START)).to_numpy() & np.isfinite(base[:, 0, 0])
        prod = calibrate.fit(base[ok], hg[ok], ag[ok], fx["div"].astype(str).to_numpy()[ok], **kw)
        js = calibrate.to_json(prod)
        js.update({"variant": chosen, "experiment_id": rec["id"], "train_window": [TRAIN_START, res["test_window"][1]]})
        ch = reg["champion"]
        p = ch["params"]
        ch["calibration"] = js
        ch["previous_version"] = ch.get("version")
        ch["version"] = (f"{__version__}+ensemble-xg-cal-hl{int(p['half_life_days'])}-k{p['kappa']:g}-elo{p['elo_k']:g}")
        ch["version_note"] = (f"{__version__}: results-only calibration layer '{chosen}' (total goals / home "
                              "advantage per division, draw & 0-0 inflation, sharpening) on top of the ensemble.")
        reg["confidence"] = champion_confidence(wf, mats[chosen], test, ch["version"])
        save_registry(reg)
        res["production"] = js
    elif reg["champion"].pop("calibration", None) is not None:
        save_registry(reg)  # a previously adopted layer that no longer passes is removed
    config.BACKTEST_DIR.mkdir(parents=True, exist_ok=True)
    (config.BACKTEST_DIR / "calibration_summary.json").write_text(json.dumps(res, indent=1, default=str))
    write_markdown(res)
    return res


def _ci(d):
    return f"{d['mean_diff']:+.5f} [{d['ci95'][0]:+.5f}, {d['ci95'][1]:+.5f}]"


def write_markdown(res):
    L = ["# Calibration layer backtest (results only)", "",
         f"Experiment `{res['experiment_id']}` · test window {res['test_window'][0]} → {res['test_window'][1]} · "
         f"n = {res['n_test']:,} matches · layer for season S fitted only on OOS matches from {TRAIN_START} to the "
         "start of S. Δ = calibrated − base ensemble (negative = better); 95% CIs by block bootstrap over refit weeks.", "",
         "Adoption rule (fixed in advance): all three Δ < 0 and the CIs of ΔRPS and Δexact-score log score entirely < 0.", "",
         f"Base ensemble: RPS {res['base']['rps']:.5f} · 1X2 log loss {res['base']['log_loss']:.5f} · "
         f"exact-score log score {res['base']['exact_log_score']:.5f}", "",
         "| Variant | RPS | ΔRPS [95% CI] | Δ1X2 log loss [95% CI] | Δexact log score [95% CI] | Eligible |",
         "|---|---|---|---|---|---|"]
    for n, v in res["variants"].items():
        d = v["delta"]
        L.append(f"| {n} | {v['summary']['rps']:.5f} | {_ci(d['rps'])} | {_ci(d['log_loss'])} | "
                 f"{_ci(d['exact_log_score'])} | {'**yes**' if v['eligible'] else 'no'} |")
    L += ["", f"**Adopted:** `{res['chosen']}`" if res["chosen"] else "**Adopted:** none (no variant passed)", ""]
    L += ["## Reliability of goal-market probabilities (model vs results, test window)", "",
          "| Market | Bin | n | base pred | base obs | calibrated pred | calibrated obs |", "|---|---|---|---|---|---|---|"]
    rc = res.get("reliability_chosen") or {}
    for mkt, v in res["reliability_base"].items():
        cb = {b["bin"]: b for b in (rc.get(mkt) or {}).get("bins", [])}
        for b in v["bins"]:
            c = cb.get(b["bin"])
            L.append(f"| {mkt} | {b['bin']} | {b['n']} | {b['pred']:.3f} | {b['obs']:.3f} | "
                     f"{(c['pred'] if c else float('nan')):.3f} | {(c['obs'] if c else float('nan')):.3f} |")
    (config.ROOT / "docs" / "CALIBRATION.md").write_text("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
