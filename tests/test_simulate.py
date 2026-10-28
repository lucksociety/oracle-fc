import numpy as np

from oraclefc.simulate import monte_carlo, score_matrix, summarise


def test_probabilities_sum_to_one():
    for lh, la, rho in [(1.4, 1.1, -0.05), (0.3, 3.2, 0.0), (2.8, 0.4, -0.12)]:
        m = score_matrix(np.array([lh]), np.array([la]), np.array([rho]))[0]
        s = summarise(m)
        assert abs(m.sum() - 1) < 1e-12
        assert abs(s["p_home"] + s["p_draw"] + s["p_away"] - 1) < 1e-12
        assert abs(sum(s["total_buckets"].values()) - 1) < 1e-9
        assert (m >= 0).all()


def test_modal_score_is_joint_mode_not_rounded_xg():
    m = score_matrix(np.array([1.6]), np.array([1.55]), np.array([0.0]))[0]
    s = summarise(m)
    i, j = np.unravel_index(m.argmax(), m.shape)
    assert (s["modal_score"]["home"], s["modal_score"]["away"]) == (i, j)
    # rounded xG would say 2-2, the joint mode is 1-1
    assert (i, j) == (1, 1)


def test_top_scores_sorted_and_xg_consistent():
    m = score_matrix(np.array([1.3]), np.array([0.9]), np.array([-0.04]))[0]
    s = summarise(m)
    ps = [t["p"] for t in s["top_scores"]]
    assert ps == sorted(ps, reverse=True) and len(ps) == 5
    assert abs(s["xg_home"] - (m.sum(1) * np.arange(m.shape[0])).sum()) < 1e-9


def test_monte_carlo_converges_to_exact():
    m = score_matrix(np.array([1.5]), np.array([1.0]), np.array([-0.05]))[0]
    mc = monte_carlo(m, n_sims=200_000)
    assert mc["max_abs_dev_vs_exact"] < 0.01
    assert mc["converged"]
