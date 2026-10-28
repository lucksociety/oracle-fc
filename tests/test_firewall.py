"""Directive Zero firewall: forecasting code must never import the market package."""
import ast
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent / "oraclefc"
FORECASTING = ["models", "simulate.py", "forecast.py", "backtest.py", "run_backtest.py", "ingest", "store.py",
               "resolve.py", "fixtures", "metrics.py", "teams.py", "governance.py", "report.py", "frozen.py",
               "experiments.py"]


def _py_files():
    for name in FORECASTING:
        p = PKG / name
        yield from (p.rglob("*.py") if p.is_dir() else [p])


def test_no_market_imports_in_forecasting_code():
    bad = []
    for f in _py_files():
        tree = ast.parse(f.read_text())
        for node in ast.walk(tree):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                mods = [node.module or ""]
            for m in mods:
                if "market" in m.split("."):
                    bad.append(f"{f.relative_to(PKG)}: {m}")
    assert not bad, bad


def test_fixture_module_never_reads_prices():
    src = (PKG / "fixtures" / "jupiter.py").read_text()
    for token in ("pricing", "buyYesPriceUsd", "sellYesPriceUsd", "includeMarkets"):
        assert token not in src.replace("# ", ""), token
