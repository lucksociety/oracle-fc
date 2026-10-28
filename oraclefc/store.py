"""Clean-layer storage (Parquet + DuckDB) and point-in-time access."""
from __future__ import annotations

import hashlib
import json

import duckdb
import pandas as pd

from . import config
from .governance import CLEAN_MATCH_SCHEMA, validate_clean_matches, now_utc_iso
from .ingest import footballdata, openfootball_cl
from .teams import core_tokens, match_team, team_key

CLEAN_PARQUET = config.CLEAN_DIR / "matches.parquet"


def _mid(row) -> str:
    s = f"{row['date']:%Y-%m-%d}|{row['div']}|{row['home']}|{row['away']}"
    return hashlib.sha1(s.encode()).hexdigest()[:14]


def _map_cl(cl: pd.DataFrame, domestic: pd.DataFrame) -> pd.DataFrame:
    by_country = {c: sorted(g["home"].unique()) for c, g in domestic.groupby("country")}
    cache: dict[tuple[str, str], tuple[str, str, str]] = {}

    def resolve(raw: str, cc: str):
        k = (raw, cc)
        if k not in cache:
            country = config.UEFA_CC.get(cc)
            if country and country in by_country:
                m = match_team(raw, by_country[country])
                if m.canonical:
                    cache[k] = (country, m.canonical, team_key(country, m.canonical))
                    return cache[k]
            cache[k] = (country or cc, raw, team_key(cc, core_tokens(raw).title() or raw))
        return cache[k]

    rows = []
    for r in cl.itertuples(index=False):
        hc, hn, hk = resolve(r.home_raw, r.home_cc)
        ac, an, ak = resolve(r.away_raw, r.away_cc)
        rows.append({"date": r.date, "kickoff": r.kickoff, "div": "UCL", "country": "Europe", "season": r.season,
                     "home": hn, "away": an, "home_key": hk, "away_key": ak, "hg": r.hg, "ag": r.ag,
                     "neutral": bool(r.neutral), "source": "openfootball", "source_file": r.source_file})
    return pd.DataFrame(rows)


def build(seasons: list[str] | None = None, include_extra: bool = True, include_cl: bool = True) -> pd.DataFrame:
    seasons = seasons or config.season_codes()
    frames, prov = footballdata.fetch_main(seasons)
    if include_extra:
        f2, p2 = footballdata.fetch_extra()
        frames += f2
        prov += p2
    dom = footballdata.normalise(frames)
    dom["home_key"] = [team_key(c, h) for c, h in zip(dom["country"], dom["home"])]
    dom["away_key"] = [team_key(c, a) for c, a in zip(dom["country"], dom["away"])]
    parts = [dom]
    if include_cl:
        cl, p3 = openfootball_cl.fetch_cl()
        prov += p3
        if len(cl):
            parts.append(_map_cl(cl, dom))
    df = pd.concat(parts, ignore_index=True)
    df = df[pd.to_datetime(df["date"]) >= pd.Timestamp(f"{config.FIRST_SEASON_START}-07-01")]
    for col in CLEAN_MATCH_SCHEMA:
        if col not in df.columns:
            df[col] = pd.NA
    df["kickoff"] = df["kickoff"].fillna("").astype(str)
    for col, dt in CLEAN_MATCH_SCHEMA.items():
        if dt == "Int64":
            df[col] = pd.to_numeric(df[col], errors="coerce").round().astype("Int64")
        elif dt == "float64":
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
        elif dt == "bool":
            df[col] = df[col].fillna(False).astype(bool)
        elif dt == "string":
            df[col] = df[col].astype("string")
    df["date"] = pd.to_datetime(df["date"])
    df["match_id"] = df.apply(_mid, axis=1)
    df = df.drop_duplicates("match_id").sort_values(["date", "div", "home"]).reset_index(drop=True)
    df = validate_clean_matches(df[list(CLEAN_MATCH_SCHEMA)])
    config.CLEAN_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(CLEAN_PARQUET, index=False)
    meta = {"built_at": now_utc_iso(), "rows": len(df), "max_date": str(df["date"].max().date()),
            "provenance": prov}
    (config.CLEAN_DIR / "provenance.json").write_text(json.dumps(meta, indent=1))
    with duckdb.connect(str(config.DB_PATH)) as con:
        con.execute("CREATE OR REPLACE TABLE matches AS SELECT * FROM read_parquet(?)", [str(CLEAN_PARQUET)])
    return df


def load(path=None) -> pd.DataFrame:
    df = pd.read_parquet(path or CLEAN_PARQUET)
    return validate_clean_matches(df)


def data_cutoff(df: pd.DataFrame) -> str:
    return str(df["date"].max().date())


def recent_teams(df: pd.DataFrame, divs: list[str], days: int = 450) -> list[str]:
    """Canonical names of teams that played in ``divs`` within ``days`` of the data cutoff."""
    sub = df[df["div"].isin(divs) & (df["date"] >= df["date"].max() - pd.Timedelta(days=days))]
    return sorted(set(sub["home"]).union(sub["away"]))


def key_for(df: pd.DataFrame, name: str, divs: list[str]) -> str | None:
    sub = df[df["div"].isin(divs) & ((df["home"] == name) | (df["away"] == name))]
    if not len(sub):
        return None
    last = sub.iloc[-1]
    return last["home_key"] if last["home"] == name else last["away_key"]
