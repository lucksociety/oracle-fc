"""Probe: which leagues and seasons carry team xG and player xG on FotMob match pages?

Samples a few finished matches per season. Observed statistics only; no odds are read.
Usage: python -m research.xg_coverage BRA ARG USA ...
"""
from __future__ import annotations

import sys

from oraclefc.ingest import fotmob, fotmob_xg

PER_SEASON, MAX_SEASONS = 6, 7


def main(divs):
    print("div | season | finished | sampled | team xG | full parse (xG + line-ups + player minutes) | player xG rows>0")
    for div in divs:
        lid = fotmob.LEAGUES[div]
        try:
            seasons = fotmob._season_list(lid)[:MAX_SEASONS]
        except Exception as e:
            print(div, "season list failed", type(e).__name__, e)
            continue
        for s in seasons:
            try:
                body = fotmob.league(lid, s, None)
                ms = [m for m in ((body or {}).get("fixtures") or {}).get("allMatches", [])
                      if (m.get("status") or {}).get("finished") and not (m.get("status") or {}).get("cancelled")]
                step = max(1, len(ms) // PER_SEASON)
                sample = ms[step // 2::step][:PER_SEASON]
                txg = full = pxg = 0
                for m in sample:
                    d = fotmob.match_details_raw(int(m["id"]), None) or {}
                    if fotmob_xg.team_xg(d) is not None:
                        txg += 1
                    p = fotmob_xg.parse_match(d, div, div, 0)
                    if p is not None:
                        full += 1
                        pxg += any(r["xG"] > 0 for r in p[1])
                print(f"{div} | {s} | {len(ms)} | {len(sample)} | {txg} | {full} | {pxg}", flush=True)
            except Exception as e:
                print(f"{div} | {s} | failed {type(e).__name__}: {e}", flush=True)


if __name__ == "__main__":
    main(sys.argv[1:] or ["BRA"])
