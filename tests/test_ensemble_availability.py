import numpy as np
import pytest
from oraclefc.models.ensemble import combine
from oraclefc.simulate import score_matrix


def test_invalid_component_is_excluded_and_remaining_weights_renormalized():
    a = score_matrix([1.2, 1.7], [0.9, 1.1])
    b = score_matrix([2.2, 0.7], [1.9, 2.1])
    bad = b.copy(); bad[0, 3, 4] = np.nan
    out = combine([a, bad], np.array([0.3, 0.7]))
    np.testing.assert_allclose(out[0], a[0])
    np.testing.assert_allclose(out[1], 0.3*a[1] + 0.7*b[1])
    np.testing.assert_allclose(out.sum((1, 2)), 1.0)
    assert np.isnan(combine([bad[:1]], np.array([1]))).all()


def test_zero_weight_invalid_model_does_not_corrupt_valid_forecast():
    a = score_matrix([1.2], [0.9]); bad = np.full_like(a, np.nan)
    np.testing.assert_allclose(combine([a, bad], np.array([1, 0])), a)
    with pytest.raises(ValueError): combine([a, a], np.array([1, -0.1]))
