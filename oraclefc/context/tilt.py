"""Exponential tilting of a joint score matrix.

P'(h, a) ∝ P(h, a) · exp(dh·h + da·a)

For independent Poisson margins this is exactly lambda_h -> lambda_h·e^dh and
lambda_a -> lambda_a·e^da, so dh/da are log-multipliers of expected goals. It works
for any matrix (including the ensemble mixture), keeps it a valid distribution
(renormalised, sums to 1) and needs no access to model internals.
"""
from __future__ import annotations

import numpy as np


def tilt(P: np.ndarray, dh, da) -> np.ndarray:
    P = np.asarray(P, float)
    G = P.shape[-1]
    k = np.arange(G)
    dh = np.asarray(dh, float)[..., None, None]
    da = np.asarray(da, float)[..., None, None]
    W = np.exp(dh * k[:, None] + da * k[None, :])
    Q = P * W
    return Q / Q.sum(axis=(-2, -1), keepdims=True)


def fit_coefficients(P: np.ndarray, hg, ag, Xh: np.ndarray, Xa: np.ndarray, ridge: float = 2.0):
    """Maximise the exact-score log-likelihood of tilted matrices.

    dh = Xh @ beta, da = Xa @ beta (each row of Xh/Xa holds the features as they act on the
    home / away scoring rate). Ridge shrinks beta toward 0 (= no adjustment)."""
    from scipy.optimize import minimize

    G = P.shape[-1]
    hg = np.minimum(np.asarray(hg, int), G - 1)
    ag = np.minimum(np.asarray(ag, int), G - 1)
    k = np.arange(G, dtype=float)
    P = np.clip(np.asarray(P, float), 1e-300, None)
    logP_obs = np.log(P[np.arange(len(hg)), hg, ag])
    n, K = Xh.shape

    def f(b):
        dh, da = Xh @ b, Xa @ b
        Q = tilt(P, dh, da)
        Eh = (Q.sum(2) * k).sum(1)
        Ea = (Q.sum(1) * k).sum(1)
        logZ = np.log((P * np.exp(dh[:, None, None] * k[:, None] + da[:, None, None] * k[None, :])).sum((1, 2)))
        ll = logP_obs + dh * hg + da * ag - logZ
        nll = -ll.sum() + 0.5 * ridge * b @ b
        gh, ga = hg - Eh, ag - Ea
        g = -(Xh.T @ gh + Xa.T @ ga) + ridge * b
        return nll, g

    res = minimize(f, np.zeros(K), jac=True, method="L-BFGS-B")
    # approximate standard errors from the Fisher information (diagonal of inverse Hessian)
    try:
        H = res.hess_inv.todense()
        se = np.sqrt(np.clip(np.diag(H), 0, None))
    except Exception:
        se = np.full(K, np.nan)
    return res.x, se
