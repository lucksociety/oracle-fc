"""Benchmark models (Phase 7.3): historical league average, home/away rates."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .base import GoalModel


class LeagueAverage(GoalModel):
    """Both teams score at the division's average goals-per-team rate (no home effect)."""
    name = "league_avg"

    def __init__(self, window_days: int = 730):
        self.window_days = window_days

    def fit(self, df, as_of):
        d = self._train(df, as_of, self.window_days)
        g = d.groupby("div").agg(h=("hg", "sum"), a=("ag", "sum"), n=("hg", "size"))
        self.rate = ((g["h"] + g["a"]) / (2 * g["n"])).astype(float).to_dict()
        self.global_rate = float((d["hg"].sum() + d["ag"].sum()) / (2 * len(d)))
        return self

    def rates(self, fx):
        r = np.array([self.rate.get(dv, self.global_rate) for dv in fx["div"]], float)
        return r, r.copy(), np.zeros(len(fx))


class HomeAwayRate(GoalModel):
    """Division-specific home and away scoring rates (captures home advantage only)."""
    name = "home_away_rate"

    def __init__(self, window_days: int = 730):
        self.window_days = window_days

    def fit(self, df, as_of):
        d = self._train(df, as_of, self.window_days)
        g = d.groupby("div").agg(h=("hg", "mean"), a=("ag", "mean"))
        self.h, self.a = g["h"].astype(float).to_dict(), g["a"].astype(float).to_dict()
        self.gh, self.ga = float(d["hg"].mean()), float(d["ag"].mean())
        return self

    def rates(self, fx):
        h = np.array([self.h.get(dv, self.gh) for dv in fx["div"]], float)
        a = np.array([self.a.get(dv, self.ga) for dv in fx["div"]], float)
        neutral = fx["neutral"].to_numpy(bool)
        avg = (h + a) / 2
        return np.where(neutral, avg, h), np.where(neutral, avg, a), np.zeros(len(fx))
