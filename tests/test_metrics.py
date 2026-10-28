import numpy as np

from oraclefc.metrics import per_match, summary
from oraclefc.simulate import score_matrix


def test_perfect_vs_uniform():
    m = score_matrix(np.array([1.4, 1.4]), np.array([1.1, 1.1]), np.array([0.0, 0.0]))
    pm = per_match(m, np.array([1, 0]), np.array([0, 2]))
    s = summary(pm)
    assert 0 < s["rps"] < 1 and s["log_loss"] > 0 and 0 <= s["top5"] <= 1
    # RPS of a certain correct forecast is 0
    p = np.zeros((1, 11, 11)); p[0, 2, 0] = 1
    assert summary(per_match(p, np.array([2]), np.array([0])))["rps"] < 1e-12
