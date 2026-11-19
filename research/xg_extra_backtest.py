"""Does FotMob xG improve the forecast in leagues outside the top five?

Walk-forward (weekly refits, data strictly before each refit) on the leagues in
fotmob_extra_matches.parquet. Base = production ensemble weights with the xG slot fitted on goals
only (what runs today in these leagues). Challenger = the same with xG blended in at weight 0.5.
Reports challenger − base (negative = better) with a block-bootstrap 95% interval, pooled and per league.
"""
from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd

from oraclefc import config, metrics, store
from oraclefc.backtest import walk_forward
from oraclefc.context import history as H
from oraclefc.experiments import load_registry
from oraclefc.models.baselines import HomeAwayRate
from oraclefc.models.dixon_coles import TeamStrengthModel, dynamic_dc, standard_dc, xg_dc
from oraclefc.models.elo import EloGoals
from oraclefc.models.ensemble import combine


def main(start="2024-04-01"):
    df = store.load()
    um = pd.read_parquet(config.CONTEXT_DIR / "fotmob_extra_matches.parquet")
    divs = sorted(um["div"].unique())
    df = df[df["div"].isin(divs)].copy()
    mp = H.map_understat(df, um)
    for d, g in mp.groupby("div"):
        miss = g[g["match_id"].isna()]
        print(f"{d}: {len(g)} xG matches, {g['match_id'].notna().mean():.1%} linked to results; unlinked clubs: "
              f"{sorted(set(miss['home'][miss['home_key'].isna()]) | set(miss['away'][miss['away_key'].isna()]))[:12]}")
    df = H.attach_xg(df, mp)
    cov = df[df["date"] >= "2023-01-01"].groupby("div")["hxg"].agg(lambda s: s.notna().mean())
    print("share of results since 2023 with xG:", cov.round(3).to_dict())
    reg = load_registry()["champion"]
    p, w = reg["params"], reg["ensemble_weights"]
    hl, k = p["half_life_days"], p["kappa"]
    models = [dynamic_dc(hl, k), EloGoals(k=p["elo_k"]), standard_dc(), HomeAwayRate(), xg_dc(hl, k, 0.5),
              TeamStrengthModel("xg_w30", hl, 1100, k, True, True, 0.3), TeamStrengthModel("xg_w70", hl, 1100, k, True, True, 0.7)]
    wf = walk_forward(df, start, str((df["date"].max() + pd.Timedelta(days=1)).date()), models, verbose=False)
    fx = wf.fx
    hg, ag = fx["hg"].to_numpy(int), fx["ag"].to_numpy(int)
    order = ["dynamic_dc", "elo", "standard_dc", "home_away_rate", "xg_dc"]
    wts = np.array([w[n] for n in order], float)

    def ens(xg_slot):
        return combine([wf.mats[n] if n != "xg_dc" else wf.mats[xg_slot] for n in order], wts)

    base = ens("dynamic_dc")
    ok = np.isfinite(base).all(axis=(1, 2))
    blocks = fx["refit_date"].to_numpy()
    out = {}
    for label, slot in (("xG weight 0.5 (production setting)", "xg_dc"), ("xG weight 0.3", "xg_w30"), ("xG weight 0.7", "xg_w70")):
        ch = ens(slot)
        print(f"\n== {label}: challenger − base, negative = better ==")
        for name, mask in [("ALL", ok)] + [(d, ok & (fx["div"] == d).to_numpy()) for d in divs]:
            mask = mask & np.isfinite(ch).all(axis=(1, 2)) & fx["hxg"].notna().to_numpy() if False else mask & np.isfinite(ch).all(axis=(1, 2))
            if mask.sum() < 50:
                continue
            a, b = metrics.per_match(base[mask].astype(float), hg[mask], ag[mask]), metrics.per_match(ch[mask].astype(float), hg[mask], ag[mask])
            r = {m: metrics.block_bootstrap_diff(b[m], a[m], blocks[mask]) for m in ("rps", "log_loss", "exact_log_score")}
            out[f"{label}|{name}"] = {"n": int(mask.sum()), "base_log_loss": float(a["log_loss"].mean()), "base_rps": float(a["rps"].mean()), **r}
            f = lambda x: f"{x['mean_diff']:+.5f} [{x['ci95'][0]:+.5f}, {x['ci95'][1]:+.5f}]"
            print(f"{name:4s} n={mask.sum():5d} base ll {a['log_loss'].mean():.4f} | Δlog loss {f(r['log_loss'])} | ΔRPS {f(r['rps'])} | Δexact {f(r['exact_log_score'])}", flush=True)
    (config.BACKTEST_DIR / "xg_extra_summary.json").write_text(json.dumps({"start": start, "divs": divs, "results": out}, indent=1, default=float))


if __name__ == "__main__":
    main(*sys.argv[1:])
