"""One-off: run the real context refresh, then compare FotMob xG with Understat xG on matches both cover."""
import numpy as np, pandas as pd, time
from oraclefc import config
from oraclefc.ingest import understat, fotmob, fotmob_xg as F
from oraclefc.teams import match_team
pm, pp = config.CONTEXT_DIR / "understat_matches.parquet", config.CONTEXT_DIR / "understat_players.parquet"
before = pd.read_parquet(pm)
import traceback
try:
    F.fill(*F.drop_superseded(before, pd.read_parquet(pp)), season=2026)
except Exception: traceback.print_exc()
t0 = time.time(); understat.update(max_seconds=60); print(f"update took {time.time()-t0:.0f}s")
m, p = pd.read_parquet(pm), pd.read_parquet(pp)
fm = m[m.us_id >= F.OFFSET]
print("matches before", len(before), "after", len(m), "| FotMob rows", len(fm))
print(fm.groupby("div").agg(n=("us_id", "size"), first=("datetime", "min"), last=("datetime", "max")).to_string())
fp = p[p.us_id >= F.OFFSET]
print("FotMob player rows", len(fp), "| mapped to existing ids", round(float((~fp.player_id.astype(str).str.startswith("fm")).mean()), 3) if len(fp) else None, "| starters per match-side", (fp[fp.position != "Sub"].groupby(["us_id", "side"]).size().describe()[["min", "max"]].to_dict() if len(fp) else None))
print("unmapped players by club (top):")
x = fp[fp.player_id.astype(str).str.startswith("fm")].merge(fm[["us_id", "home", "away"]], on="us_id")
x["club"] = np.where(x.side == "h", x.home, x.away); print(x.groupby("club").player.nunique().sort_values(ascending=False).head(12).to_string())
print(x[["club", "player", "time"]].drop_duplicates("player").head(25).to_string(index=False))
# xG agreement on October matches that Understat has
rows = []
for div, (lg, lid) in F.LEAGUES.items():
    us = before[(before["div"] == div) & before.is_result & (before.datetime >= "2026-10-10")]
    titles = sorted(set(us.home) | set(us.away))
    for x in F.finished(fotmob.league(lid, max_age_h=6), pd.Timestamp("2026-10-10"))[:22]:
        d = fotmob.match_details_raw(x["fm_id"], max_age_h=None) or {}
        got = F.parse_match(d, div, lg, 2026)
        if not got: continue
        mm = got[0]; home = match_team(mm["home"], titles).canonical
        u = us[(us.home == home) & ((us.datetime - mm["datetime"]).abs() <= pd.Timedelta(days=1))]
        if len(u) == 1: rows.append((div, mm["hxg"], mm["axg"], float(u.hxg.iloc[0]), float(u.axg.iloc[0]), len(got[1])))
        elif home is None: print("  no club match for", mm["home"], "in", div)
c = pd.DataFrame(rows, columns=["div", "fh", "fa", "uh", "ua", "np"])
f, u = np.r_[c.fh, c.fa], np.r_[c.uh, c.ua]
print(f"overlap matches {len(c)}: FotMob mean xG {f.mean():.3f} vs Understat {u.mean():.3f} | ratio {f.mean()/u.mean():.3f} | corr {np.corrcoef(f,u)[0,1]:.3f} | mean abs diff {np.abs(f-u).mean():.3f}")
print(c.groupby("div").apply(lambda g: pd.Series({"n": len(g), "fotmob": np.r_[g.fh, g.fa].mean().round(3), "understat": np.r_[g.uh, g.ua].mean().round(3)})).to_string())
# does the model's mapping still work?
from oraclefc import store
from oraclefc.context import history as H
df = store.load(); mp = H.map_understat(df)
fmm = mp[mp.us_id >= F.OFFSET]; print("FotMob rows mapped to results:", round(float(fmm.match_id.notna().mean()), 3) if len(fmm) else None, "of", len(fmm)); print(fmm[fmm.match_id.isna()][["div", "home", "away", "datetime"]].head(12).to_string(index=False))
lh, book = H.lineup_history(mp); print("lineup features rows", len(lh), "latest", book.last_date)
print("\n=== club name check: FotMob league names vs Understat titles")
for div, (lg, lid) in F.LEAGUES.items():
    us = before[(before["div"] == div) & (before.season == 2026)]
    titles = sorted(set(us.home) | set(us.away))
    body = fotmob.league(lid, max_age_h=6) or {}
    names = sorted({t["name"] for m in (body.get("fixtures") or {}).get("allMatches", []) for t in (m["home"], m["away"])})
    miss = [n for n in names if match_team(n, titles).canonical is None]
    hit = {match_team(n, titles).canonical for n in names} - {None}
    print(div, "fotmob clubs", len(names), "unmatched:", miss, "| understat titles not hit:", sorted(set(titles) - hit))
