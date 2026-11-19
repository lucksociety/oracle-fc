"""Backfill FotMob team xG and player rows for leagues outside the top five.

Writes data/context/fotmob_extra_matches.parquet and fotmob_extra_players.parquet in the same
schema as the Understat snapshot. Nothing in the live model reads these files; they exist so the
xG component can be tested on these leagues before it is switched on.
Observed statistics only: no odds, polls or predictions are read.

Usage: python -m research.xg_backfill BRA:2023 ARG:2023 ...   (division:first season year)
"""
from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from oraclefc import config
from oraclefc.governance import assert_no_market_columns
from oraclefc.ingest import fotmob, fotmob_xg

M_PATH = config.CONTEXT_DIR / "fotmob_extra_matches.parquet"
P_PATH = config.CONTEXT_DIR / "fotmob_extra_players.parquet"


def one(job):
    mid, div, season = job
    try:
        return fotmob_xg.parse_match(fotmob.match_details_raw(mid, None) or {}, div, div, season)
    except Exception:  # noqa: BLE001
        return None


def main(args, budget_s=75 * 60):
    t0 = time.time()
    m = pd.read_parquet(M_PATH) if M_PATH.exists() else pd.DataFrame(columns=fotmob_xg.MATCH_COLS)
    p = pd.read_parquet(P_PATH) if P_PATH.exists() else pd.DataFrame()
    have = set(m["us_id"])
    for a in args:
        div, first = a.split(":")
        lid = fotmob.LEAGUES[div]
        for s in fotmob._season_list(lid):
            if int(s[:4]) < int(first) or time.time() - t0 > budget_s:
                continue
            body = fotmob.league(lid, s, None)
            todo = [(x["fm_id"], div, int(s[:4])) for x in fotmob_xg.finished(body, pd.Timestamp("2000-01-01"))
                    if fotmob_xg.OFFSET + x["fm_id"] not in have]
            with ThreadPoolExecutor(4) as ex:
                got = [g for g in ex.map(one, todo) if g is not None]
            if got:
                add_m = pd.DataFrame([g[0] for g in got])[fotmob_xg.MATCH_COLS]
                rows = [dict(r, player_id=f"fm{r['fm_player_id']}") for g in got for r in g[1]]
                add_p = pd.DataFrame(rows).drop(columns=["fm_player_id"])
                assert_no_market_columns(add_m, "fotmob extra matches"); assert_no_market_columns(add_p, "fotmob extra players")
                m = pd.concat([m, add_m], ignore_index=True); p = pd.concat([p, add_p], ignore_index=True)
                have |= set(add_m["us_id"])
                m.to_parquet(M_PATH, index=False); p.to_parquet(P_PATH, index=False)
            raw = add_m if got else None
            print(f"{div} {s}: {len(todo)} to fetch, {len(got)} parsed"
                  + (f", goals/match {(raw.hg + raw.ag).mean():.2f}, scaled xG/match {(raw.hxg + raw.axg).mean():.2f}" if got else "")
                  + f" [{time.time() - t0:.0f}s]", flush=True)
    print(f"total: {len(m)} matches, {len(p)} player rows")
    print(m.groupby(["div", "season"]).size().unstack(fill_value=0).to_string())


if __name__ == "__main__":
    main(sys.argv[1:])
