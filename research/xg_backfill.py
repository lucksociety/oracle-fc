"""Backfill FotMob team xG and player rows for the leagues outside the top five.

Usage: python -m research.xg_backfill [DIV:first_season_year ...]   (default: every league in EXTRA_LEAGUES)
Observed statistics only: no odds, polls or predictions are read.
"""
from __future__ import annotations

import sys

import pandas as pd

from oraclefc.ingest import fotmob_xg

if __name__ == "__main__":
    divs = {a.split(":")[0]: int(a.split(":")[1]) for a in sys.argv[1:]} or None
    m = fotmob_xg.fill_extra(divs, max_seconds=None, backfill=True, with_players=True)
    print(m.groupby(["div", "season"]).size().unstack(fill_value=0).to_string())
