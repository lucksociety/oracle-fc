"""Common model interface. Models only ever receive governance-validated
clean match frames (no market columns are present or accepted)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..governance import assert_no_market_columns
from ..simulate import score_matrix

FIXTURE_COLS = ["home_key", "away_key", "div", "neutral"]


class GoalModel:
    name = "base"

    def fit(self, df: pd.DataFrame, as_of: pd.Timestamp) -> "GoalModel":
        raise NotImplementedError

    def rates(self, fx: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Return (lambda_home, lambda_away, rho). NaN when a team is unknown."""
        raise NotImplementedError

    def predict_matrix(self, fx: pd.DataFrame) -> np.ndarray:
        assert_no_market_columns(fx, f"{self.name}.predict")
        lh, la, rho = self.rates(fx)
        out = np.full((len(fx), 11, 11), np.nan)
        ok = np.isfinite(lh) & np.isfinite(la)
        if ok.any():
            out[ok] = score_matrix(lh[ok], la[ok], rho[ok])
        return out

    @staticmethod
    def _train(df: pd.DataFrame, as_of, window_days: int | None):
        assert_no_market_columns(df, "training data")
        d = df[df["date"] < as_of]
        if window_days:
            d = d[d["date"] >= as_of - pd.Timedelta(days=window_days)]
        return d.dropna(subset=["hg", "ag"])
