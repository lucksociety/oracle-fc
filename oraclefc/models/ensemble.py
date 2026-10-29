"""Phase 4: linear opinion pool of joint score matrices.

Weights live on the simplex and are learned ONLY from walk-forward
out-of-sample predictions that pre-date the period being forecast (nested
walk-forward). Objective: exact-score log score (a proper scoring rule over the
full joint distribution), with a small Dirichlet-style shrink toward equal
weights to limit overfitting.
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import minimize


def fit_weights(mats: list[np.ndarray], hg, ag, shrink: float = 1.0) -> np.ndarray:
    G = mats[0].shape[-1] - 1
    hg, ag = np.minimum(np.asarray(hg, int), G), np.minimum(np.asarray(ag, int), G)
    n = len(hg)
    P = np.stack([m[np.arange(n), hg, ag] for m in mats], 1)  # (n, K)
    ok = np.isfinite(P).all(1)
    P = np.clip(P[ok], 1e-12, None)
    K = P.shape[1]

    def f(z):
        w = np.exp(z - z.max())
        w /= w.sum()
        mix = P @ w
        nll = -np.log(mix).sum() - shrink * np.log(w).sum()
        g_w = -(P / mix[:, None]).sum(0) - shrink / w
        g_z = w * (g_w - (w * g_w).sum())
        return nll, g_z

    res = minimize(f, np.zeros(K), jac=True, method="L-BFGS-B")
    w = np.exp(res.x - res.x.max())
    return w / w.sum()


def combine(mats: list[np.ndarray], w: np.ndarray) -> np.ndarray:
    stack = np.stack(mats)
    weights = np.asarray(w, float)
    if len(weights) != len(mats) or not np.isfinite(weights).all() or (weights < 0).any() or weights.sum() <= 0:
        raise ValueError("ensemble weights must be finite, nonnegative and have positive mass")
    valid = np.isfinite(stack).all(axis=(-2, -1)) & (stack >= 0).all(axis=(-2, -1))
    mass = np.where(np.isfinite(stack), stack, 0).sum(axis=(-2, -1))
    valid &= np.isclose(mass, 1.0, atol=1e-6)
    effective = weights.reshape((-1,) + (1,) * (valid.ndim - 1)) * valid
    denom = effective.sum(axis=0)
    numerator = (np.where(valid[..., None, None], stack, 0) * effective[..., None, None]).sum(axis=0)
    return np.divide(numerator, denom[..., None, None], out=np.full_like(numerator, np.nan),
                     where=denom[..., None, None] > 0)
