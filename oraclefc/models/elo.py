"""Model G: independent goal-based Elo, derived solely from match results.

Ratings are updated sequentially (World-Football-Elo style margin multiplier).
New teams enter at their division's current mean rating. Ratings are mapped
to scoring rates with a Poisson regression fitted only on matches before the
cutoff, using each match's *pre-match* rating difference:

log λ_home = a_div + b·Δ/400 ,  log λ_away = c_div − d·Δ/400,  Δ = R_h + HFA − R_a
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from .. import config
from .base import GoalModel

TIER_START = {0: 1600, 1: 1500, 2: 1380, 3: 1280, 4: 1200, 5: 1120}


def _mult(gd: int) -> float:
    gd = abs(gd)
    if gd <= 1:
        return 1.0
    if gd == 2:
        return 1.5
    return (11 + gd) / 8


class EloGoals(GoalModel):
    name = "elo"

    def __init__(self, k: float = 22.0, hfa: float = 65.0, window_days: int = 1100):
        self.k, self.hfa, self.window_days = k, hfa, window_days
        self._state_date = None
        self.R: dict[str, float] = {}
        self.div_of: dict[str, str] = {}
        self._pre: dict[str, float] = {}   # match_id -> pre-match Δ

    def _replay(self, df: pd.DataFrame, as_of: pd.Timestamp):
        if self._state_date is not None and as_of < self._state_date:
            self._state_date, self.R, self.div_of, self._pre = None, {}, {}, {}
        d = df[df["date"] < as_of]
        if self._state_date is not None:
            d = d[d["date"] >= self._state_date]
        d = d.dropna(subset=["hg", "ag"])
        R, div_of, pre = self.R, self.div_of, self._pre
        div_sum: dict[str, list[float]] = {}
        for r in d.itertuples(index=False):
            for key in (r.home_key, r.away_key):
                if key not in R:
                    dv = r.div if r.div != "UCL" else "UCL"
                    members = [R[t] for t, v in div_of.items() if v == dv] if dv != "UCL" else []
                    tier = config.ALL_DIVISIONS.get(dv, ("", "", 3))[2] if dv != "UCL" else 3
                    R[key] = float(np.mean(members)) if len(members) >= 6 else TIER_START.get(tier, 1200)
            if r.div != "UCL":
                div_of[r.home_key] = r.div
                div_of[r.away_key] = r.div
            hfa = 0.0 if r.neutral else self.hfa
            delta = R[r.home_key] + hfa - R[r.away_key]
            pre[r.match_id] = delta
            e = 1 / (1 + 10 ** (-delta / 400))
            s = 1.0 if r.hg > r.ag else (0.5 if r.hg == r.ag else 0.0)
            chg = self.k * _mult(int(r.hg) - int(r.ag)) * (s - e)
            R[r.home_key] += chg
            R[r.away_key] -= chg
        self._state_date = as_of

    def fit(self, df, as_of):
        as_of = pd.Timestamp(as_of)
        self._replay(df, as_of)
        d = self._train(df, as_of, self.window_days)
        d = d[d["match_id"].isin(self._pre.keys())]
        delta = d["match_id"].map(self._pre).to_numpy(float) / 400
        divs = pd.Index(sorted(d["div"].unique()))
        di = divs.get_indexer(d["div"])
        yh, ya = d["hg"].to_numpy(float), d["ag"].to_numpy(float)
        nd = len(divs)

        def f(x):
            a, c, b, dd = x[:nd], x[nd:2 * nd], x[-2], x[-1]
            eh, ea = a[di] + b * delta, c[di] - dd * delta
            lh, la = np.exp(eh), np.exp(ea)
            nll = -np.sum(yh * eh - lh + ya * ea - la)
            gh, ga = lh - yh, la - ya
            g = np.concatenate([np.bincount(di, gh, nd), np.bincount(di, ga, nd),
                                [np.sum(gh * delta)], [-np.sum(ga * delta)]])
            return nll, g

        x0 = np.concatenate([np.full(nd, 0.3), np.full(nd, 0.1), [0.5, 0.5]])
        res = minimize(f, x0, jac=True, method="L-BFGS-B")
        self.a = pd.Series(res.x[:nd], divs)
        self.c = pd.Series(res.x[nd:2 * nd], divs)
        self.b, self.d = float(res.x[-2]), float(res.x[-1])
        self.as_of = as_of
        return self

    def rating(self, key, div_hint=None):
        if key in self.R:
            return self.R[key]
        return np.nan

    def rates(self, fx):
        lh, la = np.full(len(fx), np.nan), np.full(len(fx), np.nan)
        for i, r in enumerate(fx.itertuples(index=False)):
            rh, ra = self.rating(r.home_key), self.rating(r.away_key)
            if np.isnan(rh) or np.isnan(ra):
                continue
            delta = (rh + (0.0 if r.neutral else self.hfa) - ra) / 400
            dv = r.div if r.div in self.a.index else None
            a = self.a[dv] if dv else self.a.mean()
            c = self.c[dv] if dv else self.c.mean()
            if r.neutral:
                a = c = (a + c) / 2
            lh[i] = np.exp(a + self.b * delta)
            la[i] = np.exp(c - self.d * delta)
        return lh, la, np.zeros(len(fx))
