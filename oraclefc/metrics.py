"""Proper scoring rules and evaluation metrics."""
from __future__ import annotations

import numpy as np

from .simulate import outcome_probs


def outcome_index(hg, ag):
    hg, ag = np.asarray(hg), np.asarray(ag)
    return np.where(hg > ag, 0, np.where(hg == ag, 1, 2))


def per_match(mats: np.ndarray, hg: np.ndarray, ag: np.ndarray) -> dict[str, np.ndarray]:
    """Per-match scores for a stack of joint matrices (n, G+1, G+1)."""
    G = mats.shape[-1] - 1
    hg, ag = np.asarray(hg, int), np.asarray(ag, int)
    n = len(hg)
    p = outcome_probs(mats)
    o = outcome_index(hg, ag)
    onehot = np.eye(3)[o]
    ll = -np.log(np.clip(p[np.arange(n), o], 1e-12, None))
    brier = ((p - onehot) ** 2).sum(1)
    cp, co = np.cumsum(p, 1)[:, :2], np.cumsum(onehot, 1)[:, :2]
    rps = ((cp - co) ** 2).sum(1) / 2
    ps = mats[np.arange(n), np.minimum(hg, G), np.minimum(ag, G)]
    exact_ll = -np.log(np.clip(ps, 1e-12, None))
    flat = mats.reshape(n, -1)
    rank = (flat > ps[:, None]).sum(1) + 1
    k = np.arange(G + 1)
    eh = (mats.sum(2) * k).sum(1)
    ea = (mats.sum(1) * k).sum(1)
    return {"log_loss": ll, "brier": brier, "rps": rps, "exact_log_score": exact_ll,
            "top1": (rank <= 1).astype(float), "top3": (rank <= 3).astype(float),
            "top5": (rank <= 5).astype(float), "abs_err_home": np.abs(eh - hg),
            "abs_err_away": np.abs(ea - ag), "abs_err_total": np.abs(eh + ea - hg - ag),
            "sq_err_goals": ((eh - hg) ** 2 + (ea - ag) ** 2) / 2,
            "p_home": p[:, 0], "p_draw": p[:, 1], "p_away": p[:, 2], "outcome": o.astype(float)}


def summary(pm: dict[str, np.ndarray]) -> dict[str, float]:
    keys = ["log_loss", "rps", "brier", "exact_log_score", "top1", "top3", "top5",
            "abs_err_home", "abs_err_away", "abs_err_total"]
    out = {k: float(np.mean(pm[k])) for k in keys}
    out["mae_goals"] = (out.pop("abs_err_home") + out.pop("abs_err_away")) / 2
    out["rmse_goals"] = float(np.sqrt(np.mean(pm["sq_err_goals"])))
    out["mae_total"] = out.pop("abs_err_total")
    out["n"] = int(len(pm["log_loss"]))
    return out


def calibration_table(pm, bins=10):
    """Reliability of all three outcome probabilities pooled."""
    p = np.concatenate([pm["p_home"], pm["p_draw"], pm["p_away"]])
    o = pm["outcome"].astype(int)
    y = np.concatenate([(o == 0), (o == 1), (o == 2)]).astype(float)
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges) - 1, 0, bins - 1)
    rows = []
    for b in range(bins):
        m = idx == b
        if m.sum() < 30:
            continue
        rows.append({"bin": f"{edges[b]:.1f}-{edges[b+1]:.1f}", "n": int(m.sum()),
                     "mean_pred": float(p[m].mean()), "observed": float(y[m].mean())})
    return rows


def favourite_calibration(pm, bins=(0.33, 0.4, 0.5, 0.6, 0.7, 0.8, 1.01)):
    """Hit-rate of the most-likely outcome by its predicted probability (used for MODEL CONFIDENCE)."""
    p = np.stack([pm["p_home"], pm["p_draw"], pm["p_away"]], 1)
    fav = p.argmax(1)
    pmax = p.max(1)
    hit = (fav == pm["outcome"].astype(int)).astype(float)
    rows = []
    for lo, hi in zip(bins[:-1], bins[1:]):
        m = (pmax >= lo) & (pmax < hi)
        if m.sum() < 20:
            continue
        se = float(np.sqrt(hit[m].mean() * (1 - hit[m].mean()) / m.sum()))
        rows.append({"lo": lo, "hi": min(hi, 1.0), "n": int(m.sum()), "mean_pred": float(pmax[m].mean()),
                     "hit_rate": float(hit[m].mean()), "se": se})
    return rows


def block_bootstrap_diff(a: np.ndarray, b: np.ndarray, blocks: np.ndarray, n_boot: int = 2000,
                         seed: int = 0) -> dict:
    """Mean difference a−b with a block bootstrap CI (blocks = e.g. match weeks),
    accounting for correlation between matches played in the same week."""
    rng = np.random.default_rng(seed)
    diff = np.asarray(a) - np.asarray(b)
    ub = np.unique(blocks)
    sums = np.array([diff[blocks == u].sum() for u in ub])
    cnts = np.array([(blocks == u).sum() for u in ub])
    stats = []
    for _ in range(n_boot):
        s = rng.integers(0, len(ub), len(ub))
        stats.append(sums[s].sum() / cnts[s].sum())
    lo, hi = np.quantile(stats, [0.025, 0.975])
    stats = np.asarray(stats)
    return {"mean_diff": float(diff.mean()), "ci95": [float(lo), float(hi)],
            "p_le_0": float((stats <= 0).mean()), "n_blocks": int(len(ub))}
