"""Supplemental domestic results. Only completed 90-minute scores enter training."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json

import pandas as pd

from .. import config
from ..governance import Provenance, now_utc_iso
from .http import get_json

BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"


def parse_results(data, div, year, url):
    if div not in config.SUPPLEMENTAL_DIVISIONS or div in config.WOMEN_DIVISIONS:
        return
    country = config.SUPPLEMENTAL_DIVISIONS[div][0]
    for event in data.get("events", []):
        if event.get("status", {}).get("type", {}).get("name") != "STATUS_FULL_TIME":
            continue
        competitions = event.get("competitions", [])
        if len(competitions) != 1:
            continue
        match = competitions[0]
        sides = {c.get("homeAway"): c for c in match.get("competitors", [])}
        if set(sides) != {"home", "away"} or len(match["competitors"]) != 2:
            continue
        try:
            home, away = sides["home"], sides["away"]
            kickoff = datetime.fromisoformat(event["date"].replace("Z", "+00:00"))
            ht, at = home["team"], away["team"]
            hg, ag = int(home["score"]), int(away["score"])
            if not ht["id"] or not at["id"] or ht["id"] == at["id"] or not ht["displayName"] or not at["displayName"]:
                continue
        except (KeyError, TypeError, ValueError):
            continue
        if kickoff.year != year or kickoff.date() >= datetime.now(timezone.utc).date() or min(hg, ag) < 0:
            continue
        yield {"date": pd.Timestamp(kickoff.date()), "kickoff": kickoff.strftime("%H:%M"), "div": div,
               "country": country, "season": str(year), "home": ht["displayName"], "away": at["displayName"],
               "home_key": f"{country}:espn-{ht['id']}", "away_key": f"{country}:espn-{at['id']}",
               "hg": hg, "ag": ag, "neutral": bool(match.get("neutralSite")), "source": "espn-results",
               "source_file": url}


def _fetch(task):
    div, slug, year = task
    url = f"{BASE}/{slug}/scoreboard?dates={year}&limit=1000"
    cache = config.RAW_DIR / "espn-results" / f"{slug}-{year}.json"
    body = get_json(url, cache, max_age_h=6 if year == datetime.now(timezone.utc).year else 168, retries=1, timeout=8)
    if body is None and cache.exists():
        body = get_json(url, cache)
    if not isinstance(body, dict):
        return [], None
    rows = list(parse_results(body, div, year, url))
    if not rows:
        return [], None
    provenance = Provenance("espn-results", url, now_utc_iso(), len(rows),
                            ["kickoff", "team identity", "final score", "neutral venue"],
                            sha256=hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest())
    return rows, provenance.to_dict()


def fetch():
    year = datetime.now(timezone.utc).year
    tasks = [(div, slug, y) for div, slug in config.SUPPLEMENTAL_FEEDS.items() for y in range(year - 2, year + 1)]
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(_fetch, tasks))
    return pd.DataFrame([row for rows, _ in results for row in rows]), [p for _, p in results if p]
