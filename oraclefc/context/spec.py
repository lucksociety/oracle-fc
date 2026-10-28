"""Pre-specified feature transforms (fixed BEFORE looking at backtest results).

The same functions build the historical design matrix (backtest) and the live
features (forecast), so validated coefficients mean the same thing in both.
"""
from __future__ import annotations

import numpy as np

# family -> parameter names (order = coefficient vector order)
FAMILIES = {
    "rest": ["short_rest_own", "short_rest_opp", "congestion_own", "congestion_opp"],
    "travel": ["travel_home_boost", "travel_away_penalty"],
    "weather": ["rain", "wind", "heat", "cold"],
    "lineup": ["xi_attack_own", "xi_continuity_own", "xi_continuity_opp", "backup_gk_opp"],
}


def short_rest(days):
    """1.0 at <=2 days' rest, 0 at >=5 days (NaN -> 0: unknown = no adjustment)."""
    d = np.asarray(days, float)
    return np.nan_to_num(np.clip((5.0 - d) / 3.0, 0.0, 1.0))


def congestion(n21):
    """Matches played in the previous 21 days above 4, scaled to [0, 1]."""
    return np.nan_to_num(np.clip((np.asarray(n21, float) - 4.0) / 3.0, 0.0, 1.0))


def travel(km):
    return np.nan_to_num(np.log1p(np.asarray(km, float) / 100.0))


def weather(precip_mm_2h, wind_ms, temp_c):
    p = np.nan_to_num(np.minimum(np.asarray(precip_mm_2h, float), 10.0) / 10.0)
    w = np.nan_to_num(np.clip((np.asarray(wind_ms, float) - 8.0) / 6.0, 0.0, 1.5))
    t = np.asarray(temp_c, float)
    hot = np.nan_to_num(np.clip((t - 24.0) / 8.0, 0.0, 1.5))
    cold = np.nan_to_num(np.clip((2.0 - t) / 8.0, 0.0, 1.5))
    return p, w, hot, cold


def design(family: str, f: dict) -> tuple[np.ndarray, np.ndarray]:
    """Return (Xh, Xa) for one family from a dict of per-match arrays."""
    if family == "rest":
        sh, sa = short_rest(f["rest_h"]), short_rest(f["rest_a"])
        ch, ca = congestion(f["n21_h"]), congestion(f["n21_a"])
        return np.c_[sh, sa, ch, ca], np.c_[sa, sh, ca, ch]
    if family == "travel":
        t = travel(f["travel_km"]) * (1.0 - np.asarray(f.get("neutral", 0), float))
        z = np.zeros_like(t)
        return np.c_[t, z], np.c_[z, t]
    if family == "weather":
        p, w, hot, cold = weather(f["precip_mm_2h"], f["wind_ms"], f["temp_c"])
        X = np.c_[p, w, hot, cold]
        return X, X.copy()
    if family == "lineup":
        Ah, Aa = (np.nan_to_num(np.asarray(f[k], float)) for k in ("A_h", "A_a"))
        Ch, Ca = (np.nan_to_num(np.asarray(f[k], float)) for k in ("C_h", "C_a"))
        Gh, Ga = (np.nan_to_num(np.asarray(f[k], float)) for k in ("G_h", "G_a"))
        return np.c_[Ah, Ch, Ca, Ga], np.c_[Aa, Ca, Ch, Gh]
    raise KeyError(family)


def deltas(family: str, f: dict, beta) -> tuple[np.ndarray, np.ndarray]:
    Xh, Xa = design(family, f)
    b = np.asarray(beta, float)
    return Xh @ b, Xa @ b
