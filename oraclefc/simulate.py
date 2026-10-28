"""Match simulation engine: exact joint score distribution + Monte Carlo.

All outputs are derived from a joint matrix P[x, y] = P(home=x, away=y).
"""
from __future__ import annotations

import math

import numpy as np
from scipy.stats import poisson

MAX_GOALS = 10  # matrix is (MAX_GOALS+1)^2; residual tail mass is folded in by renormalisation


def dc_tau(lh, la, rho, G=MAX_GOALS):
    """Dixon–Coles low-score dependence multipliers, shape (..., G+1, G+1)."""
    lh, la, rho = np.asarray(lh, float), np.asarray(la, float), np.asarray(rho, float)
    tau = np.ones(lh.shape + (G + 1, G + 1))
    tau[..., 0, 0] = 1 - lh * la * rho
    tau[..., 0, 1] = 1 + lh * rho
    tau[..., 1, 0] = 1 + la * rho
    tau[..., 1, 1] = 1 - rho
    return np.clip(tau, 1e-6, None)


def score_matrix(lh, la, rho=0.0, G=MAX_GOALS):
    """Independent-Poisson (optionally Dixon–Coles adjusted) joint score matrix.

    Works on scalars or 1-D arrays (returns (n, G+1, G+1))."""
    lh = np.atleast_1d(np.asarray(lh, float))
    la = np.atleast_1d(np.asarray(la, float))
    rho = np.broadcast_to(np.asarray(rho, float), lh.shape)
    k = np.arange(G + 1)
    ph = poisson.pmf(k[None, :], lh[:, None])
    pa = poisson.pmf(k[None, :], la[:, None])
    m = ph[:, :, None] * pa[:, None, :]
    m = m * dc_tau(lh, la, rho, G)
    m /= m.sum(axis=(1, 2), keepdims=True)
    return m


def outcome_probs(m):
    """(home, draw, away) from a matrix or a stack of matrices."""
    m = np.asarray(m)
    home = np.tril(m, -1).sum(axis=(-2, -1))
    draw = np.trace(m, axis1=-2, axis2=-1)
    away = np.triu(m, 1).sum(axis=(-2, -1))
    return np.stack([home, draw, away], axis=-1)


def _quantile(dist, q):
    c = np.cumsum(dist)
    return int(np.searchsorted(c, q - 1e-12))


def summarise(m: np.ndarray, top_n: int = 5) -> dict:
    """Every required simulation output from a single joint matrix."""
    m = np.asarray(m, float)
    assert m.ndim == 2
    G = m.shape[0] - 1
    k = np.arange(G + 1)
    ph, pa = m.sum(axis=1), m.sum(axis=0)
    tot = np.zeros(2 * G + 1)
    for x in range(G + 1):
        for y in range(G + 1):
            tot[x + y] += m[x, y]
    hda = outcome_probs(m)
    flat = [(m[x, y], x, y) for x in range(G + 1) for y in range(G + 1)]
    flat.sort(reverse=True)
    top = [{"home": int(x), "away": int(y), "p": float(p)} for p, x, y in flat[:top_n]]
    btts = float(m[1:, 1:].sum())
    totals_over = {f"over_{t + 0.5:g}": float(tot[t + 1:].sum()) for t in range(0, 7)}
    eh, ea = float((k * ph).sum()), float((k * pa).sum())
    gd = {}
    for x in range(G + 1):
        for y in range(G + 1):
            gd[x - y] = gd.get(x - y, 0.0) + m[x, y]
    gd_vals = np.array(sorted(gd))
    gd_p = np.array([gd[v] for v in gd_vals])
    gd_c = np.cumsum(gd_p)
    return {
        "p_home": float(hda[0]), "p_draw": float(hda[1]), "p_away": float(hda[2]),
        "xg_home": eh, "xg_away": ea, "xg_total": eh + ea,
        "median_total": _quantile(tot, 0.5),
        "modal_score": top[0],
        "top_scores": top,
        "btts": btts,
        "totals_over": totals_over,
        "total_buckets": {"0-1": float(tot[:2].sum()), "2": float(tot[2]), "3": float(tot[3]),
                          "4": float(tot[4]), "5+": float(tot[5:].sum())},
        "clean_sheet_home": float(pa[0]), "clean_sheet_away": float(ph[0]),
        "home_goal_dist": [float(v) for v in ph[:7]] + [float(ph[7:].sum())],
        "away_goal_dist": [float(v) for v in pa[:7]] + [float(pa[7:].sum())],
        "intervals": {
            "home_goals_80": [_quantile(ph, 0.1), _quantile(ph, 0.9)],
            "away_goals_80": [_quantile(pa, 0.1), _quantile(pa, 0.9)],
            "total_goals_80": [_quantile(tot, 0.1), _quantile(tot, 0.9)],
            "goal_diff_80": [int(gd_vals[np.searchsorted(gd_c, 0.1 - 1e-12)]),
                             int(gd_vals[np.searchsorted(gd_c, 0.9 - 1e-12)])],
        },
        "score_grid": [[round(float(m[x, y]), 6) for y in range(7)] for x in range(7)],
        "mass_check": float(m.sum()),
    }


def monte_carlo(m: np.ndarray, n_sims: int = 200_000, seed: int = 7, batch: int = 50_000,
                tol: float = 0.002, max_sims: int = 1_000_000) -> dict:
    """Sample full matches from the joint matrix with adaptive stopping.

    Reports Monte Carlo standard errors (sampling error only — NOT model
    uncertainty) and the max |MC − exact| deviation as a convergence check."""
    rng = np.random.default_rng(seed)
    G = m.shape[0] - 1
    p = np.asarray(m, float).ravel()
    p = p / p.sum()
    counts = np.zeros_like(p)
    n = 0
    while n < max_sims:
        draw = rng.multinomial(min(batch, max_sims - n), p)
        counts += draw
        n += int(draw.sum())
        est = counts / n
        mc = est.reshape(G + 1, G + 1)
        hda = outcome_probs(mc)
        se = np.sqrt(hda * (1 - hda) / n)
        if n >= n_sims and se.max() < tol:
            break
    exact = outcome_probs(m)
    return {
        "n_sims": n, "seed": seed,
        "p_home": float(hda[0]), "p_draw": float(hda[1]), "p_away": float(hda[2]),
        "se": [float(s) for s in se],
        "max_abs_dev_vs_exact": float(np.abs(hda - exact).max()),
        "converged": bool(se.max() < tol),
    }


def param_uncertainty(lh: float, la: float, sd_log_h: float, sd_log_a: float, rho: float = 0.0,
                      n: int = 400, seed: int = 11) -> dict:
    """Propagate (approximate) parameter uncertainty in the scoring rates.

    Samples log-rates from a normal approximation and reports 80% intervals of
    the resulting outcome probabilities and expected goals (model uncertainty,
    separate from match randomness and MC error)."""
    rng = np.random.default_rng(seed)
    zh = rng.standard_normal(n)
    za = rng.standard_normal(n)
    lhs = lh * np.exp(sd_log_h * zh - 0.5 * sd_log_h ** 2)
    las = la * np.exp(sd_log_a * za - 0.5 * sd_log_a ** 2)
    mats = score_matrix(lhs, las, rho)
    hda = outcome_probs(mats)
    q = lambda a: [float(np.quantile(a, 0.1)), float(np.quantile(a, 0.9))]
    return {"xg_home_80": q(lhs), "xg_away_80": q(las), "p_home_80": q(hda[:, 0]),
            "p_draw_80": q(hda[:, 1]), "p_away_80": q(hda[:, 2]), "n_draws": n,
            "sd_log_rate": [float(sd_log_h), float(sd_log_a)]}


def log_score_exact(m, hg, ag):
    G = m.shape[-1] - 1
    return -math.log(max(float(m[min(hg, G), min(ag, G)]), 1e-12))
