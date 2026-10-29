"""Results-only post-ensemble calibration of the joint score matrix (Directive Zero safe).

    Q(h, a) ∝ P(h, a)^(1+t) · exp(dh·h + da·a + dd·1[h=a] + d0·1[h=a=0])

* dh / da  — log-multipliers of home / away expected goals (total-goals level and home
             advantage), global + per-division deviations shrunk toward 0 by a ridge prior;
* dd / d0  — draw and 0-0 inflation (low-score dependence the Poisson-type Elo component
             lacks), global + per-division;
* t        — global sharpening (t > 0) / flattening (t < 0) of the whole distribution.

Fitted by maximum likelihood of the observed exact score on walk-forward OUT-OF-SAMPLE
ensemble matrices only (never on market data), and in backtests nested by season: the
layer applied to season S is fitted only on matches dated before S starts.
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import minimize

TERMS = ("h", "a", "draw", "nil")


def _cells(G: int):
    k = np.arange(G, dtype=float)
    H, A = np.meshgrid(k, k, indexing="ij")
    return {"h": H, "a": A, "draw": (H == A).astype(float), "nil": ((H == 0) & (A == 0)).astype(float)}


def design(divs, levels: list[str], terms=TERMS, per_div=("h", "a")) -> tuple[np.ndarray, list[tuple]]:
    """Per-match coefficient-selection matrix: columns = (term, None) global + (term, div) deviations."""
    divs = np.asarray(divs)
    cols = [(t, None) for t in terms] + [(t, d) for t in per_div for d in levels]
    X = np.zeros((len(divs), len(cols)))
    for j, (t, d) in enumerate(cols):
        X[:, j] = 1.0 if d is None else (divs == d)
    return X, cols


def apply(P: np.ndarray, coef: dict, divs, sharpen: float = 0.0) -> np.ndarray:
    """Apply fitted coefficients {(term, div|None): value} to matrices P (n, G, G)."""
    P = np.asarray(P, float)
    n, G = P.shape[0], P.shape[-1]
    cells = _cells(G)
    divs = np.asarray(divs)
    logw = np.zeros((n, G, G))
    for t in TERMS:
        v = np.full(n, coef.get((t, None), 0.0))
        for (tt, d), b in coef.items():
            if tt == t and d is not None:
                v = v + b * (divs == d)
        logw += v[:, None, None] * cells[t][None]
    logP = np.log(np.clip(P, 1e-300, None))
    L = (1.0 + sharpen) * logP + logw
    L -= L.max(axis=(1, 2), keepdims=True)
    Q = np.exp(L)
    return (Q / Q.sum(axis=(1, 2), keepdims=True)).astype(P.dtype)


def fit(P: np.ndarray, hg, ag, divs, levels=None, terms=TERMS, per_div=("h", "a"), ridge_global: float = 1.0,
        ridge_div: float = 50.0, sharpen: bool = True, max_n: int | None = None, seed: int = 0) -> dict:
    """ML fit with ridge (global terms lightly, per-division deviations strongly shrunk)."""
    P = np.asarray(P, float)
    G = P.shape[-1]
    hg = np.minimum(np.asarray(hg, int), G - 1)
    ag = np.minimum(np.asarray(ag, int), G - 1)
    divs = np.asarray(divs)
    ok = np.isfinite(P[:, 0, 0])
    P, hg, ag, divs = P[ok], hg[ok], ag[ok], divs[ok]
    if max_n and len(P) > max_n:
        idx = np.random.default_rng(seed).choice(len(P), max_n, replace=False)
        P, hg, ag, divs = P[idx], hg[idx], ag[idx], divs[idx]
    if levels is None:
        u, c = np.unique(divs, return_counts=True)
        levels = [d for d, k in zip(u, c) if k >= 300]
    X, cols = design(divs, levels, terms, per_div)
    cells = _cells(G)
    F = np.stack([cells[t] for t, _ in cols], 0)          # (K, G, G) cell features per column
    term_idx = {t: [j for j, (tt, _) in enumerate(cols) if tt == t] for t in terms}
    logP = np.log(np.clip(P, 1e-300, None))
    n = len(P)
    ar = np.arange(n)
    obs_feat = np.stack([cells[t][hg, ag] for t, _ in cols], 1) * X   # (n, K)
    obs_logP = logP[ar, hg, ag]
    K = len(cols)
    lam = np.array([ridge_global if d is None else ridge_div for _, d in cols])
    Tf = np.stack([cells[t] for t in terms], 0)           # (T, G, G)

    def f(z):
        b, s = z[:K], (z[K] if sharpen else 0.0)
        # per-match coefficient of each term
        v = np.stack([X[:, term_idx[t]] @ b[term_idx[t]] for t in terms], 1)   # (n, T)
        L = (1 + s) * logP + np.einsum("nt,tij->nij", v, Tf)
        m = L.max(axis=(1, 2), keepdims=True)
        Q = np.exp(L - m)
        Z = Q.sum(axis=(1, 2))
        Q /= Z[:, None, None]
        logZ = np.log(Z) + m[:, 0, 0]
        ll = (1 + s) * obs_logP + (obs_feat * b).sum(1) - logZ
        nll = -ll.sum() + 0.5 * (lam * b * b).sum() + (0.5 * 10.0 * s * s if sharpen else 0.0)
        Ef = np.einsum("nij,tij->nt", Q, Tf)              # E_Q[term feature]
        g_b = np.zeros(K)
        for ti, t in enumerate(terms):
            for j in term_idx[t]:
                g_b[j] = -((cells[t][hg, ag] - Ef[:, ti]) * X[:, j]).sum()
        g_b += lam * b
        out_g = [g_b]
        if sharpen:
            ElogP = (Q * logP).sum(axis=(1, 2))
            out_g.append([-(obs_logP - ElogP).sum() + 10.0 * s])
        return nll, np.concatenate(out_g)

    z0 = np.zeros(K + (1 if sharpen else 0))
    res = minimize(f, z0, jac=True, method="L-BFGS-B", options={"maxiter": 500})
    coef = {c: float(v) for c, v in zip(cols, res.x[:K]) if abs(v) > 1e-9}
    return {"coef": coef, "sharpen": float(res.x[K]) if sharpen else 0.0, "n": int(n), "levels": list(levels),
            "converged": bool(res.success)}


def to_json(cal: dict) -> dict:
    return {"coef": [[t, d, round(v, 6)] for (t, d), v in cal["coef"].items()],
            "sharpen": round(cal["sharpen"], 6), "n": cal["n"], "levels": cal["levels"]}


def from_json(js: dict) -> dict:
    return {"coef": {(t, d): v for t, d, v in js["coef"]}, "sharpen": js.get("sharpen", 0.0)}
