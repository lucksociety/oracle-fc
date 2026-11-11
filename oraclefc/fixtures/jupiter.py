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
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

import requests

from .. import config
from ..sports_policy import allowed, fixture_allowed
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


def _get(url: str, params: dict, retries: int = 4):
    for i in range(retries):
        try:
            r = requests.get(url, params=params, headers=_headers(), timeout=20)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as exc:
            status=getattr(getattr(exc,'response',None),'status_code',None)
            if status is not None and status!=429 and status<500: raise
            if i+1==retries: raise
            time.sleep(min(8,2**i+1))


def sanitise_event(ev: dict) -> Fixture | None:
    """Allowlist copy of the identity fields of one event. Returns None for non-match events."""
    event_id = str(ev.get("eventId") or "")
    if not event_id.startswith("POLY-"):
        return None
    md = ev.get("metadata") or {}
    title = md.get("title") or ""
    m = TITLE_RE.match(title)
    begin = ev.get("beginAt")
    if not m or not begin:
        return None  # outrights / futures ("EPL: 2027 Champion") are not matches
    if not fixture_allowed({"subcategory":ev.get("subcategory"),"competition":md.get("league"),"home_name":m.group("h"),"away_name":m.group("a")}):
        return None
    if "soccer" not in (ev.get("tags") or []):
        return None
    kickoff = datetime.fromtimestamp(int(begin), timezone.utc).isoformat()
    return Fixture(
        event_id=event_id, home_name=m.group("h").strip(), away_name=m.group("a").strip(),
        competition=str(md.get("league") or ev.get("subcategory") or ""),
        subcategory=str(ev.get("subcategory") or ""), kickoff_utc=kickoff, slug=str(md.get("slug") or ""))


def fetch_all_soccer(use_cache: bool = True, through_date: str | None = None, tz: str = config.USER_TZ) -> list[Fixture]:
    cached = None
    if use_cache and CACHE.exists() and time.time()-CACHE.stat().st_mtime<CACHE_TTL:
        try: cached=json.loads(CACHE.read_text())
        except (ValueError,OSError): pass
    if cached and cached.get('scope')=='upcoming-men-v2' and (cached.get('complete') or through_date and cached.get('through_date','')>=through_date):
        return [Fixture(**d) for d in cached['fixtures'] if d['event_id'].startswith('POLY-') and fixture_allowed(d)]
    end_time=(datetime.fromisoformat(through_date).replace(tzinfo=ZoneInfo(tz))+timedelta(days=1)).timestamp() if through_date else None
    previous=0;ordered=True;complete=False
    out, start, page = [], 0, 100
    while True:
        js = _get(f"{BASE}/events", {"category": "sports", "tags": "soccer", "filter":"upcoming", "start": start,
                                     "end": start + page, "sortBy": "beginAt", "sortDirection": "asc"})
        for ev in js.get("data", []):
            fx = sanitise_event(ev)
            if fx:
                out.append(fx)
        times=[int(e['beginAt']) for e in js.get('data',[]) if str(e.get('beginAt','')).isdigit()]
        ordered=ordered and times==sorted(times) and (not times or times[0]>=previous)
        if times: previous=times[-1]
        if not js.get('pagination',{}).get('hasNext'):
            complete=True;break
        # The requested date is complete once the sorted feed reaches tomorrow.
        if end_time and ordered and times and times[-1]>=end_time:break
        if start>=5000:raise requests.HTTPError('Jupiter fixture pagination exceeded safety limit; refusing a partial slate')
        start += page
        time.sleep(0.25 if os.environ.get("JUPITER_API_KEY") else 2.1)
    seen, uniq = set(), []
    for f in out:
        if f.event_id not in seen:
            seen.add(f.event_id)
            uniq.append(f)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps({"scope":"upcoming-men-v2", "complete":complete, "through_date":through_date, "fetched_at": now_utc_iso(), "fixtures": [f.to_dict() for f in uniq]}))
    return uniq


def fixtures_for_date(date: str, tz: str = config.USER_TZ, use_cache: bool = True) -> list[Fixture]:
    # Full-day inventory must include settled/started fixtures and unsupported men's leagues.
    from .polymarket import fixtures_for_date as full_day_fixtures
    return full_day_fixtures(date, tz=tz, use_cache=use_cache)
