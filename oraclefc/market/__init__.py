"""POST-HOC MARKET COMPARISON ONLY.

This package is physically separated from the forecasting engine. No module in
oraclefc.models / simulate / forecast / backtest / ingest / resolve / fixtures
may import it (enforced by tests/test_firewall.py). It runs strictly *after*
forecasts are frozen and never feeds anything back into the models.
"""
