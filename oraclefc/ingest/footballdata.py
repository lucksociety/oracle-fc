"""football-data.co.uk ingestion.

Raw CSVs contain bookmaker odds next to the factual match data. Raw files are
kept only in data/raw (gitignored) and pass through
``governance.filter_football_data_columns`` which keeps an explicit allowlist
and drops every other column *before* anything is written to the clean layer.
"""
from __future__ import annotations

import hashlib
import io
import time
from pathlib import Path

import pandas as pd
import requests

from .. import config
from ..governance import Provenance, filter_football_data_columns, now_utc_iso

UA = {"User-Agent": "oracle-fc/1.0 (research; results only)"}


def _download(url: str, dest: Path, max_age_hours: float = 12.0) -> bytes | None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and (time.time() - dest.stat().st_mtime) < max_age_hours * 3600:
        return dest.read_bytes()
    for attempt in range(4):
        try:
            r = requests.get(url, headers=UA, timeout=60)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            if not r.content.strip():
                return None
            dest.write_bytes(r.content)
            return r.content
        except requests.RequestException:
            time.sleep(2 * (attempt + 1))
    return dest.read_bytes() if dest.exists() else None


def _read_csv(content: bytes) -> pd.DataFrame:
    for enc in ("utf-8-sig", "latin-1"):
        try:
            df = pd.read_csv(io.BytesIO(content), encoding=enc, on_bad_lines="skip")
            break
        except UnicodeDecodeError:
            continue
    df = df.loc[:, [c for c in df.columns if not str(c).startswith("Unnamed")]]
    return df.dropna(how="all")


def _parse_dates(s: pd.Series) -> pd.Series:
    d = pd.to_datetime(s, format="%d/%m/%Y", errors="coerce")
    d2 = pd.to_datetime(s, format="%d/%m/%y", errors="coerce")
    return d.fillna(d2)


def fetch_main(seasons: list[str], divisions: list[str] | None = None, sleep: float = 0.3):
    divisions = divisions or list(config.MAIN_DIVISIONS)
    frames, prov = [], []
    for season in seasons:
        for div in divisions:
            url = f"{config.FOOTBALL_DATA_BASE}/mmz4281/{season}/{div}.csv"
            content = _download(url, config.RAW_DIR / "football-data" / season / f"{div}.csv")
            if content is None:
                continue
            raw = _read_csv(content)
            if "HomeTeam" not in raw.columns:
                continue
            clean, dropped = filter_football_data_columns(raw)
            clean["season"] = season
            clean["div"] = div
            clean["source_file"] = url
            frames.append(clean)
            prov.append(Provenance("football-data.co.uk", url, now_utc_iso(), len(clean), list(clean.columns),
                                   dropped, hashlib.sha256(content).hexdigest()).to_dict())
            time.sleep(sleep)
    return frames, prov


def fetch_extra(codes: list[str] | None = None):
    codes = codes or list(config.EXTRA_LEAGUES)
    frames, prov = [], []
    for code in codes:
        url = f"{config.FOOTBALL_DATA_BASE}/new/{code}.csv"
        content = _download(url, config.RAW_DIR / "football-data" / "new" / f"{code}.csv")
        if content is None:
            continue
        raw = _read_csv(content)
        clean, dropped = filter_football_data_columns(raw)
        clean["div"] = code
        clean["season"] = clean.pop("season_raw").astype(str)
        clean = clean.drop(columns=[c for c in ("country_raw", "league_raw") if c in clean.columns])
        clean["source_file"] = url
        frames.append(clean)
        prov.append(Provenance("football-data.co.uk", url, now_utc_iso(), len(clean), list(clean.columns),
                               dropped, hashlib.sha256(content).hexdigest()).to_dict())
    return frames, prov


def normalise(frames: list[pd.DataFrame]) -> pd.DataFrame:
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    df["date"] = _parse_dates(df["date"].astype(str))
    df = df.dropna(subset=["date", "home", "away", "hg", "ag"])
    df["country"] = df["div"].map(lambda d: config.ALL_DIVISIONS[d][0])
    df["source"] = "football-data.co.uk"
    df["neutral"] = False
    return df
