"""UEFA Champions League results from openfootball (football.txt format).

Used only as factual results that link the strength of different domestic
leagues (cross-league translation). Regulation-time (90') scores are used;
extra-time and shoot-outs are separated out.
"""
from __future__ import annotations

import hashlib
import re
from datetime import date

import pandas as pd
import requests

from .. import config
from ..governance import Provenance, now_utc_iso

MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}
DATE_RE = re.compile(r"^\s+(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+([A-Z][a-z]{2})\s+(\d{1,2})(?:\s+(\d{4}))?\s*$")
MATCH_RE = re.compile(
    r"^\s+(?:(\d{1,2}[:.]\d{2})\s+)?(?P<h>.+?)\s+\((?P<hc>[A-Z]{3})\)\s+v\s+(?P<a>.+?)\s+\((?P<ac>[A-Z]{3})\)\s+"
    r"(?P<rest>.+)$")
SCORE_RE = re.compile(r"(\d+)-(\d+)")


def parse_cl_text(text: str, season: str) -> pd.DataFrame:
    start_year = int(season[:4])
    cur: date | None = None
    rows = []
    final_stage = False
    for line in text.splitlines():
        if line.startswith("▪"):
            final_stage = "Final" in line and "Finals," in line and line.strip().endswith("Final")
            continue
        m = DATE_RE.match(line)
        if m:
            mon, day, yr = MONTHS[m.group(1)], int(m.group(2)), m.group(3)
            year = int(yr) if yr else (start_year if mon >= 7 else start_year + 1)
            cur = date(year, mon, day)
            continue
        m = MATCH_RE.match(line)
        if not m or cur is None:
            continue
        rest = m.group("rest")
        if "a.e.t" in rest or "pen" in rest:
            paren = re.search(r"\((\d+)-(\d+)", rest)
            if not paren:
                continue
            hg, ag = int(paren.group(1)), int(paren.group(2))
        else:
            s = SCORE_RE.match(rest.strip())
            if not s:
                continue  # not played yet
            hg, ag = int(s.group(1)), int(s.group(2))
        rows.append({
            "date": pd.Timestamp(cur), "kickoff": m.group(1) or "", "home_raw": m.group("h").strip(),
            "home_cc": m.group("hc"), "away_raw": m.group("a").strip(), "away_cc": m.group("ac"),
            "hg": hg, "ag": ag, "neutral": final_stage, "season": season,
        })
    return pd.DataFrame(rows)


def fetch_cl(first_start: int = config.FIRST_SEASON_START):
    frames, prov = [], []
    today = date.today()
    last = today.year if today.month >= 7 else today.year - 1
    for y in range(first_start, last + 1):
        season = f"{y}-{(y + 1) % 100:02d}"
        url = f"{config.OPENFOOTBALL_CL_BASE}/{season}/cl.txt"
        try:
            r = requests.get(url, timeout=60)
        except requests.RequestException:
            continue
        if r.status_code != 200:
            continue
        df = parse_cl_text(r.text, season)
        df["source_file"] = url
        frames.append(df)
        prov.append(Provenance("openfootball", url, now_utc_iso(), len(df),
                               ["date", "teams", "regulation score"], [],
                               hashlib.sha256(r.content).hexdigest()).to_dict())
    return (pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()), prov
