import pandas as pd
import pytest

from oraclefc.governance import (MarketContamination, assert_no_market_columns, assert_no_market_keys,
                                 assert_no_price_keys, filter_football_data_columns, is_prohibited_key)


def test_bookmaker_columns_are_prohibited():
    for c in ["B365H", "B365D", "PSCH", "MaxH", "AvgC>2.5", "BbAvH", "AHh", "B365AHH", "BFEA", "P>2.5",
              "implied_prob", "market_price", "buyYesPriceUsd", "odds_home", "volume24hr"]:
        assert is_prohibited_key(c), c


def test_results_columns_allowed():
    for c in ["FTHG", "FTAG", "HomeTeam", "AwayTeam", "HS", "AST", "HC", "HY", "Date", "Div"]:
        assert not is_prohibited_key(c), c


def test_football_data_filter_drops_every_odds_column():
    raw = pd.DataFrame({"Div": ["E0"], "Date": ["01/08/2025"], "HomeTeam": ["A"], "AwayTeam": ["B"],
                        "FTHG": [1], "FTAG": [0], "B365H": [1.9], "PSCH": [2.0], "MaxC>2.5": [1.8],
                        "AHh": [-0.5], "Referee": ["X"]})
    clean, dropped = filter_football_data_columns(raw)
    assert "B365H" in dropped and "PSCH" in dropped and "MaxC>2.5" in dropped and "AHh" in dropped
    assert not [c for c in clean.columns if is_prohibited_key(c)]


def test_model_input_with_odds_raises():
    with pytest.raises(MarketContamination):
        assert_no_market_columns(pd.DataFrame({"home_key": ["a"], "B365H": [2.0]}), "test")


def test_nested_market_keys_raise():
    with pytest.raises(MarketContamination):
        assert_no_market_keys({"fixture": {"home": "A", "pricing": {"buyYesPriceUsd": 1}}})


def test_forecast_output_price_guard():
    assert_no_price_keys({"simulation": {"totals_over": {"over_2.5": 0.5}, "p_home": 0.4}})
    with pytest.raises(MarketContamination):
        assert_no_price_keys({"simulation": {"market_mid": 0.5}})
