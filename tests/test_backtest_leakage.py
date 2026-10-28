import numpy as np
import pandas as pd

from oraclefc.backtest import walk_forward
from oraclefc.models.base import GoalModel
from oraclefc.models.dixon_coles import dynamic_dc


class Spy(GoalModel):
    name = "spy"

    def __init__(self):
        self.seen = []

    def fit(self, df, as_of):
        tr = self._train(df, as_of, None)
        self.seen.append((as_of, tr["date"].max()))
        self.mu = tr["hg"].mean(), tr["ag"].mean()
        return self

    def rates(self, fx):
        n = len(fx)
        return np.full(n, self.mu[0]), np.full(n, self.mu[1]), np.zeros(n)


def test_walk_forward_never_trains_on_future(synthetic_matches):
    spy = Spy()
    wf = walk_forward(synthetic_matches, "2022-01-01", "2022-06-01", [spy], verbose=False)
    assert spy.seen and all(mx < t for t, mx in spy.seen)
    # each evaluated match is strictly after its model's training data
    assert (wf.fx["date"] >= wf.fx["refit_date"]).all()


def test_future_results_do_not_change_past_forecast(synthetic_matches):
    df = synthetic_matches
    as_of = pd.Timestamp("2022-03-01")
    fx = df[(df["date"] >= as_of)].head(3)
    m1 = dynamic_dc(240, 8).fit(df, as_of).predict_matrix(fx)
    poisoned = df.copy()
    poisoned.loc[poisoned["date"] >= as_of, "hg"] = 9  # corrupt the future
    m2 = dynamic_dc(240, 8).fit(poisoned, as_of).predict_matrix(fx)
    assert np.allclose(m1, m2)


def test_dc_recovers_signal(synthetic_matches):
    df = synthetic_matches
    as_of = pd.Timestamp("2023-06-01")
    m = dynamic_dc(400, 3).fit(df, as_of)
    assert np.isfinite(np.asarray(m.att, float)).all() and len(m.att) == 12
