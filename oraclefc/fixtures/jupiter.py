"""Fixture discovery from the Jupiter prediction-market API.

Used ONLY to learn which games exist on a date (teams, competition, kickoff).
Events are requested *without* markets, and every event is copied through an
explicit field allowlist — volume, prices, orderbooks and any other market
information are never copied, never stored and never reach a model.
(Prices live in ``oraclefc.market``, which model code is forbidden to import.)

API: GET https://api.jup.ag/prediction/v1/events?category=sports&tags=soccer
     (public, keyless; an optional x-api-key raises rate limits).
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests

from .. import config
from ..governance import assert_no_market_keys, now_utc_iso

BASE = os.environ.get("JUPITER_API_BASE", "https://api.jup.ag/prediction/v1")
CACHE = config.DATA_DIR / "cache" / "jupiter_fixtures.json"
CACHE_TTL = 600  # seconds

TITLE_RE = re.compile(r"^\s*(?P<h>.+?)\s+vs\.?\s+(?P<a>.+?)\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class Fixture:
    event_id: str
    home_name: str
    away_name: str
    competition: str
    subcategory: str
    kickoff_utc: str
    slug: str
    source: str = "jupiter-fixtures"

    def to_dict(self) -> dict:
        d = asdict(self)
        assert_no_market_keys(d, "fixture")
        return d

    def local_date(self, tz: str = config.USER_TZ) -> str:
        return datetime.fromisoformat(self.kickoff_utc).astimezone(ZoneInfo(tz)).date().isoformat()


def _headers():
    h = {"User-Agent": "oracle-fc/1.0"}
    key = os.environ.get("JUPITER_API_KEY")
    if key:
        h["x-api-key"] = key
    return h


def _get(url: str, params: dict, retries: int = 6):
    for i in range(retries):
        r = requests.get(url, params=params, headers=_headers(), timeout=30)
        if r.status_code == 429:
            time.sleep(min(30, 2 ** i + 1))
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("Jupiter API rate limit persisted (HTTP 429); set JUPITER_API_KEY or retry later")


def sanitise_event(ev: dict) -> Fixture | None:
    """Allowlist copy of the identity fields of one event. Returns None for non-match events."""
    md = ev.get("metadata") or {}
    title = md.get("title") or ""
    m = TITLE_RE.match(title)
    begin = ev.get("beginAt")
    if not m or not begin:
        return None  # outrights / futures ("EPL: 2027 Champion") are not matches
    if "soccer" not in (ev.get("tags") or []):
        return None
    kickoff = datetime.fromtimestamp(int(begin), timezone.utc).isoformat()
    return Fixture(
        event_id=str(ev.get("eventId")), home_name=m.group("h").strip(), away_name=m.group("a").strip(),
        competition=str(md.get("league") or ev.get("subcategory") or ""),
        subcategory=str(ev.get("subcategory") or ""), kickoff_utc=kickoff, slug=str(md.get("slug") or ""))


def fetch_all_soccer(use_cache: bool = True) -> list[Fixture]:
    if use_cache and CACHE.exists() and time.time() - CACHE.stat().st_mtime < CACHE_TTL:
        return [Fixture(**d) for d in json.loads(CACHE.read_text())["fixtures"]]
    out, start, page = [], 0, 100
    while True:
        js = _get(f"{BASE}/events", {"category": "sports", "tags": "soccer", "start": start,
                                     "end": start + page, "sortBy": "beginAt", "sortDirection": "asc"})
        for ev in js.get("data", []):
            fx = sanitise_event(ev)
            if fx:
                out.append(fx)
        if not js.get("pagination", {}).get("hasNext") or start > 5000:
            break
        start += page
        time.sleep(0.6)
    seen, uniq = set(), []
    for f in out:
        if f.event_id not in seen:
            seen.add(f.event_id)
            uniq.append(f)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps({"fetched_at": now_utc_iso(), "fixtures": [f.to_dict() for f in uniq]}))
    return uniq


def fixtures_for_date(date: str, tz: str = config.USER_TZ, use_cache: bool = True) -> list[Fixture]:
    fx = [f for f in fetch_all_soccer(use_cache) if f.local_date(tz) == date]
    return sorted(fx, key=lambda f: (f.kickoff_utc, f.competition, f.home_name))
