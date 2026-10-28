"""Central configuration: paths, competitions, seasons."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(os.environ.get("ORACLEFC_ROOT", Path(__file__).resolve().parent.parent))
DATA_DIR = Path(os.environ.get("ORACLEFC_DATA", ROOT / "data"))
RAW_DIR = DATA_DIR / "raw"            # untouched downloads (gitignored; contain odds columns)
CLEAN_DIR = DATA_DIR / "clean"        # governance-filtered parquet
CONTEXT_DIR = DATA_DIR / "context"    # committed allow-listed context snapshots (Understat players, FotMob venues)
DB_PATH = DATA_DIR / "oraclefc.duckdb"
FORECAST_DIR = DATA_DIR / "forecasts"         # frozen, immutable forecasts
MARKET_DIR = DATA_DIR / "market_snapshots"    # post-hoc market snapshots (never read by models)
MODEL_DIR = DATA_DIR / "models"
EXPERIMENT_LOG = ROOT / "experiments" / "experiments.jsonl"
REGISTRY_PATH = ROOT / "experiments" / "registry.json"
BACKTEST_DIR = ROOT / "experiments" / "backtests"

USER_TZ = os.environ.get("ORACLEFC_TZ", "America/New_York")

FOOTBALL_DATA_BASE = "https://football-data.co.uk"

# football-data.co.uk "main" divisions: code -> (country, competition name, tier)
MAIN_DIVISIONS: dict[str, tuple[str, str, int]] = {
    "E0": ("England", "Premier League", 1),
    "E1": ("England", "Championship", 2),
    "E2": ("England", "League One", 3),
    "E3": ("England", "League Two", 4),
    "EC": ("England", "National League", 5),
    "SC0": ("Scotland", "Premiership", 1),
    "SC1": ("Scotland", "Championship", 2),
    "SC2": ("Scotland", "League One", 3),
    "SC3": ("Scotland", "League Two", 4),
    "D1": ("Germany", "Bundesliga", 1),
    "D2": ("Germany", "2. Bundesliga", 2),
    "I1": ("Italy", "Serie A", 1),
    "I2": ("Italy", "Serie B", 2),
    "SP1": ("Spain", "La Liga", 1),
    "SP2": ("Spain", "Segunda Division", 2),
    "F1": ("France", "Ligue 1", 1),
    "F2": ("France", "Ligue 2", 2),
    "N1": ("Netherlands", "Eredivisie", 1),
    "B1": ("Belgium", "Pro League", 1),
    "P1": ("Portugal", "Primeira Liga", 1),
    "T1": ("Turkey", "Super Lig", 1),
    "G1": ("Greece", "Super League", 1),
}

# football-data.co.uk "extra" leagues (one file per country, all seasons)
EXTRA_LEAGUES: dict[str, tuple[str, str, int]] = {
    "ARG": ("Argentina", "Primera Division", 1),
    "AUT": ("Austria", "Bundesliga", 1),
    "BRA": ("Brazil", "Serie A", 1),
    "CHN": ("China", "Super League", 1),
    "DNK": ("Denmark", "Superliga", 1),
    "FIN": ("Finland", "Veikkausliiga", 1),
    "IRL": ("Ireland", "Premier Division", 1),
    "JPN": ("Japan", "J1 League", 1),
    "MEX": ("Mexico", "Liga MX", 1),
    "NOR": ("Norway", "Eliteserien", 1),
    "POL": ("Poland", "Ekstraklasa", 1),
    "ROU": ("Romania", "Liga 1", 1),
    "SWE": ("Sweden", "Allsvenskan", 1),
    "SWZ": ("Switzerland", "Super League", 1),
    "USA": ("USA", "MLS", 1),
}

ALL_DIVISIONS = {**MAIN_DIVISIONS, **EXTRA_LEAGUES, "UCL": ("Europe", "UEFA Champions League", 0)}

# Season codes for football-data main files (e.g. "2324" = 2023/24)
FIRST_SEASON_START = int(os.environ.get("ORACLEFC_FIRST_SEASON", "2016"))


def season_codes(first_start: int = FIRST_SEASON_START, last_start: int | None = None) -> list[str]:
    import datetime as _dt

    today = _dt.date.today()
    if last_start is None:
        last_start = today.year if today.month >= 7 else today.year - 1
    return [f"{y % 100:02d}{(y + 1) % 100:02d}" for y in range(first_start, last_start + 1)]


# UEFA Champions League seasons from openfootball (cross-league link)
OPENFOOTBALL_CL_BASE = "https://raw.githubusercontent.com/openfootball/champions-league/master"

# openfootball country codes -> our country names
UEFA_CC = {
    "ENG": "England", "SCO": "Scotland", "GER": "Germany", "ITA": "Italy", "ESP": "Spain",
    "FRA": "France", "NED": "Netherlands", "BEL": "Belgium", "POR": "Portugal", "TUR": "Turkey",
    "GRE": "Greece", "AUT": "Austria", "SUI": "Switzerland", "DEN": "Denmark", "NOR": "Norway",
    "SWE": "Sweden", "MCO": "France", "POL": "Poland", "ROU": "Romania", "IRL": "Ireland", "FIN": "Finland",
}

# Jupiter subcategory -> candidate data divisions (where the two teams are looked up)
EUROPE_ALL = [d for d, v in ALL_DIVISIONS.items() if v[0] not in {"Argentina", "Brazil", "China", "Japan", "Mexico", "USA"}]
JUPITER_SUBCATEGORY_DIVS: dict[str, list[str]] = {
    "epl": ["E0"], "elc": ["E1"], "el1": ["E2"], "el2": ["E3"],
    "efl": ["E0", "E1", "E2", "E3", "EC"], "fac": ["E0", "E1", "E2", "E3", "EC"],
    "sea": ["I1"], "itb": ["I2"], "ser": ["I2"], "cit": ["I1", "I2"],
    "lal": ["SP1"], "es2": ["SP2"], "cdr": ["SP1", "SP2"],
    "bun": ["D1"], "bl2": ["D2"], "dfb": ["D1", "D2"],
    "fl1": ["F1"], "fl2": ["F2"], "cdf": ["F1", "F2"],
    "ere": ["N1"], "por": ["P1"], "tur": ["T1"], "gre": ["G1"], "bel1": ["B1"],
    "scop": ["SC0"], "sco": ["SC0", "SC1"],
    "aut": ["AUT"], "fin1": ["FIN"], "mex": ["MEX"], "pol": ["POL"], "chi": ["CHN"],
    "bra": ["BRA"], "arg": ["ARG"], "mls": ["USA"], "jap": ["JPN"], "nor": ["NOR"],
    "swe": ["SWE"], "den": ["DNK"], "swi": ["SWZ"], "rom": ["ROU"], "irl": ["IRL"],
    "ucl": EUROPE_ALL, "uel": EUROPE_ALL, "ucol": EUROPE_ALL,
}
