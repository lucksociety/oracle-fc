import numpy as np
from scipy.stats import poisson

from oraclefc import calibrate


def _mats(lh, la, G=11):
    k = np.arange(G)
    P = poisson.pmf(k[None, :, None], lh[:, None, None]) * poisson.pmf(k[None, None, :], la[:, None, None])
    return P / P.sum((1, 2), keepdims=True)


def test_identity_and_normalisation():
    P = _mats(np.array([1.4, 0.9]), np.array([1.0, 1.2]))
    Q = calibrate.apply(P, {}, np.array(["E0", "E0"]), 0.0)
    assert np.allclose(P, Q)
    Q = calibrate.apply(P, {("h", None): 0.1, ("draw", "E0"): 0.2}, np.array(["E0", "I1"]), 0.05)
    assert np.allclose(Q.sum((1, 2)), 1.0)
    # draw term only applies to E0
    d = lambda M: np.trace(M)
    assert d(Q[0]) > d(calibrate.apply(P, {("h", None): 0.1}, np.array(["E0", "I1"]), 0.05)[0])


def test_fit_recovers_goal_inflation():
    rng = np.random.default_rng(0)
    n = 6000
    lh, la = rng.uniform(0.8, 2.0, n), rng.uniform(0.6, 1.5, n)
    P = _mats(lh, la)
    hg, ag = rng.poisson(lh * 1.15), rng.poisson(la * 1.15)
    cal = calibrate.fit(P, hg, ag, np.array(["X"] * n), sharpen=False, per_div=())
    assert abs(cal["coef"][("h", None)] - np.log(1.15)) < 0.05
    assert abs(cal["coef"][("a", None)] - np.log(1.15)) < 0.06


def test_json_roundtrip():
    cal = {"coef": {("h", None): 0.1, ("a", "E0"): -0.02}, "sharpen": 0.01, "n": 5, "levels": ["E0"]}
    back = calibrate.from_json(calibrate.to_json(cal))
    assert back["coef"] == {("h", None): 0.1, ("a", "E0"): -0.02}


def test_tot_term_identity_when_absent_and_normalised():
    P = _mats(np.array([0.7, 2.2]), np.array([0.5, 1.6]))
    Q = calibrate.apply(P, {("tot", None): -0.2}, np.array(["E0", "E0"]), 0.0)
    assert np.allclose(Q.sum((1, 2)), 1.0)
    k = np.arange(P.shape[-1])
    tot = lambda M: (M * (k[:, None] + k[None, :])).sum()
    assert tot(Q[0]) > tot(P[0]) and tot(Q[1]) < tot(P[1])   # g < 0 pulls totals toward the centre
