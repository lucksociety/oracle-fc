"""Data governance: the market-information firewall (Directive Zero).

Every dataset that reaches a model passes through this module:

* explicit allowlist of permitted *providers* and *fields*;
* a denylist detector for market-derived columns/keys (odds, prices,
  implied probabilities, consensus picks, ...);
* provenance records describing where each table came from.

Anything not on the allowlist is dropped *before* it is stored in the clean
layer; anything matching a prohibited pattern raises ``MarketContamination``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Iterable, Mapping

import pandas as pd


class MarketContamination(RuntimeError):
    """Raised when market-derived information is detected in a model input."""


# ---------------------------------------------------------------- providers
PERMITTED_PROVIDERS = {
    "football-data.co.uk": "Historical results & match statistics (odds columns are dropped at ingestion)",
    "openfootball": "Public-domain UEFA Champions League results (football.txt)",
    "jupiter-fixtures": "Fixture identity only (teams, competition, kickoff). Prices never pass this layer.",
    "user-input": "Manually entered fixture (home, away, date, competition)",
}

# ------------------------------------------------------------------- fields
# Canonical clean match schema (the ONLY columns a model may see)
CLEAN_MATCH_SCHEMA: dict[str, str] = {
    "match_id": "string",
    "date": "datetime64[ns]",
    "kickoff": "string",
    "div": "string",
    "country": "string",
    "season": "string",
    "home": "string",
    "away": "string",
    "home_key": "string",
    "away_key": "string",
    "hg": "Int64",
    "ag": "Int64",
    "hthg": "Int64",
    "htag": "Int64",
    "hs": "Int64",
    "as_": "Int64",
    "hst": "Int64",
    "ast": "Int64",
    "hc": "Int64",
    "ac": "Int64",
    "hy": "Int64",
    "ay": "Int64",
    "hr": "Int64",
    "ar": "Int64",
    "hxg": "float64",
    "axg": "float64",
    "neutral": "bool",
    "source": "string",
    "source_file": "string",
}

# football-data.co.uk raw columns we accept -> clean column
FOOTBALL_DATA_ALLOWED = {
    "Div": "div", "Date": "date", "Time": "kickoff", "HomeTeam": "home", "AwayTeam": "away",
    "FTHG": "hg", "FTAG": "ag", "HTHG": "hthg", "HTAG": "htag", "HS": "hs", "AS": "as_",
    "HST": "hst", "AST": "ast", "HC": "hc", "AC": "ac", "HY": "hy", "AY": "ay", "HR": "hr",
    "AR": "ar", "HxG": "hxg", "AxG": "axg",
    # extra-league files
    "Country": "country_raw", "League": "league_raw", "Season": "season_raw", "Home": "home",
    "Away": "away", "HG": "hg", "AG": "ag",
}
# Result columns are derivable from goals; we keep only goals (FTR/HTR/Res dropped as redundant)

# ------------------------------------------------------------ denylist
# Column / key names that indicate market information. Case-insensitive.
_BOOKMAKER_PREFIXES = (
    "B365", "BW", "IW", "LB", "PS", "WH", "SJ", "VC", "GB", "BS", "SO", "SB", "SY", "BF", "BFD", "BFE",
    "BMGM", "BV", "CL", "PP", "SKB", "1XB", "Max", "Avg", "Bb", "P>", "P<",
)
_PROHIBITED_KEY_RE = re.compile(
    r"(odds|price|implied|moneyline|money_line|spread|handicap|^ah|ahh|aha|ahch|ahca|over|under|"
    r"vig|overround|juice|bookmaker|sportsbook|bet|wager|tip|pick|consensus|prediction|predicted|"
    r"forecast|probab|market|line_?move|volume|liquidity|orderbook|bid|ask|yes_?price|no_?price|"
    r"buyyes|sellyes|buyno|sellno|pricing|>2\.5|<2\.5|power_?rank|^bb[a-z0-9>]|^(max|avg)[a-z>])",
    re.IGNORECASE,
)


def is_prohibited_key(name: str) -> bool:
    """True when a column/key name looks market-derived."""
    n = str(name).strip()
    if not n:
        return False
    if _PROHIBITED_KEY_RE.search(n):
        return True
    for p in _BOOKMAKER_PREFIXES:
        # bookmaker code followed by H/D/A/C(losing)/>/< suffixes, e.g. B365H, PSCH, MaxC>2.5
        if re.fullmatch(re.escape(p) + r"C?(H|D|A|>2\.5|<2\.5|AHH|AHA|CH|CD|CA)", n, re.IGNORECASE):
            return True
    return False


def prohibited_columns(columns: Iterable[str]) -> list[str]:
    return [c for c in columns if is_prohibited_key(c)]


def assert_no_market_columns(df: pd.DataFrame, context: str = "") -> None:
    bad = prohibited_columns(df.columns)
    if bad:
        raise MarketContamination(f"Market-derived columns reached {context or 'a model input'}: {bad[:10]}")


def assert_no_market_keys(obj, context: str = "", _path: str = "") -> None:
    """Recursively scan a JSON-like object for prohibited keys."""
    if isinstance(obj, Mapping):
        for k, v in obj.items():
            if is_prohibited_key(k):
                raise MarketContamination(f"Prohibited key '{_path}{k}' in {context or 'object'}")
            assert_no_market_keys(v, context, f"{_path}{k}.")
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            assert_no_market_keys(v, context, f"{_path}[{i}].")


def filter_football_data_columns(raw: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Keep only allowlisted columns (renamed). Returns (clean_df, dropped_columns)."""
    keep = {c: FOOTBALL_DATA_ALLOWED[c] for c in raw.columns if c in FOOTBALL_DATA_ALLOWED}
    dropped = [c for c in raw.columns if c not in keep]
    out = raw[list(keep)].rename(columns=keep)
    assert_no_market_columns(out, "football-data clean layer")
    return out, dropped


def validate_clean_matches(df: pd.DataFrame) -> pd.DataFrame:
    """Strict schema validation for the clean match table."""
    extra = set(df.columns) - set(CLEAN_MATCH_SCHEMA)
    if extra:
        raise MarketContamination(f"Columns outside the clean schema: {sorted(extra)}")
    missing = set(CLEAN_MATCH_SCHEMA) - set(df.columns)
    if missing:
        raise ValueError(f"Clean match table missing columns: {sorted(missing)}")
    assert_no_market_columns(df, "clean match table")
    if not set(df["source"].dropna().unique()) <= set(PERMITTED_PROVIDERS):
        raise MarketContamination(f"Unpermitted source in clean table: {set(df['source'].unique())}")
    bad = df[(df["hg"] < 0) | (df["ag"] < 0)]
    if len(bad):
        raise ValueError(f"{len(bad)} rows with negative goals")
    return df[list(CLEAN_MATCH_SCHEMA)]


@dataclass
class Provenance:
    provider: str
    url: str
    retrieved_at: str
    rows: int
    kept_fields: list[str]
    dropped_fields: list[str] = field(default_factory=list)
    sha256: str = ""
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

# Model *outputs* legitimately contain words like "over" (totals) and
# "probability"; they must still never carry market prices. This narrower
# check is applied to forecast outputs.
_PRICE_KEY_RE = re.compile(
    r"(odds|price|implied|overround|vig|bookmaker|sportsbook|market|bid$|^bid|ask$|^ask|"
    r"buyyes|sellyes|buyno|sellno|pricing|liquidity|orderbook|volume|edge)",
    re.IGNORECASE,
)


def assert_no_price_keys(obj, context: str = "", _path: str = "") -> None:
    if isinstance(obj, Mapping):
        for k, v in obj.items():
            if _PRICE_KEY_RE.search(str(k)):
                raise MarketContamination(f"Price key '{_path}{k}' in {context or 'object'}")
            assert_no_price_keys(v, context, f"{_path}{k}.")
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            assert_no_price_keys(v, context, f"{_path}[{i}].")
