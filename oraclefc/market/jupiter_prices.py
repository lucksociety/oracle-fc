"""Fetch Jupiter prediction-market prices for already-forecast events."""
from __future__ import annotations

import json
import os
import re
import time

import requests

from .. import config
from ..governance import now_utc_iso
from .best_bet import selections_from_event

BASE = os.environ.get("JUPITER_API_BASE", "https://api.jup.ag/prediction/v1")
GOALS_RE = re.compile(r"(\d+)\s+or more goals", re.IGNORECASE)
EXACT_RE = re.compile(r"^(?P<h>.+?)\s+(?P<hg>\d+)\s*-\s*(?P<ag>\d+)\s+(?P<a>.+)$")


def _headers():
    h = {"User-Agent": "oracle-fc/1.0"}
    if os.environ.get("JUPITER_API_KEY"):
        h["x-api-key"] = os.environ["JUPITER_API_KEY"]
    return h


def _get(url, params, retries=6):
    for i in range(retries):
        r = requests.get(url, params=params, headers=_headers(), timeout=30)
        if r.status_code == 429:
            time.sleep(min(30, 2 ** i + 1))
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("Jupiter rate-limited")


def _mid(pr: dict) -> dict:
    buy = (pr.get("buyYesPriceUsd") or 0) / 1e6
    sell = (pr.get("sellYesPriceUsd") or 0) / 1e6
    # Only quote a mid when there is a two-sided book with a sane spread.
    mid = (buy + sell) / 2 if (buy and sell and buy - sell <= 0.15) else None
    return {"ask": buy or None, "bid": sell or None, "mid": mid, "volume": pr.get("volume"),
            "spread": (buy - sell) if (buy and sell) else None}


def parse_event_markets(ev: dict, home: str, away: str) -> dict:
    out = {"moneyline": {}, "btts": None, "totals": {}, "exact": {}}
    for m in ev.get("markets") or []:
        t = m.get("sportsMarketType")
        title = (m.get("title") or "").strip()
        pr = _mid(m.get("pricing") or {})
        if m.get("status") not in (None, "open"):
            continue
        if t == "moneyline" and not m.get("isTeamMarket"):
            if title.lower() == "draw":
                out["moneyline"]["draw"] = pr
            elif title == home:
                out["moneyline"]["home"] = pr
            elif title == away:
                out["moneyline"]["away"] = pr
        elif t == "both_teams_to_score":
            out["btts"] = pr
        elif t == "totals" and title in ("Over", "Under"):
            line = m.get("sportsLine")
            if line is None:
                g = GOALS_RE.search(m.get("rulesPrimary") or "")
                line = int(g.group(1)) - 0.5 if g else None
            if line is not None:
                line = float(line)
                # market's YES side = the outcome named in the title
                p_over = pr["mid"] if title == "Over" else (1 - pr["mid"] if pr["mid"] is not None else None)
                if p_over is not None and (title == "Over" or line not in out["totals"]):
                    out["totals"][line] = {"p_over": p_over, "volume": pr.get("volume") or 0, "side": title}
        elif t == "soccer_exact_score":
            em = EXACT_RE.match(title)
            if em:
                out["exact"][f"{em.group('hg')}-{em.group('ag')}"] = pr
    return out


def snapshot(event_ids: list[str], date: str, fixtures: dict[str, dict]) -> dict:
    """Fetch and persist a market snapshot (never read by models)."""
    snap = {"fetched_at": now_utc_iso(), "date": date, "events": {}}
    for eid in event_ids:
        fx = fixtures[eid]
        try:
            ev = _get(f"{BASE}/events/{eid}", {"includeMarkets": "true", "includeAllMarkets": "true"})
        except Exception as e:  # noqa: BLE001
            snap["events"][eid] = {"error": str(e)}
            continue
        ev = ev.get("data", ev)
        snap["events"][eid] = parse_event_markets(ev, fx["home_name"], fx["away_name"])
        snap["events"][eid]["selections"] = selections_from_event(ev, fx["home_name"], fx["away_name"])
        time.sleep(0.4)
    d = config.MARKET_DIR / date
    d.mkdir(parents=True, exist_ok=True)
    (d / f"snapshot_{snap['fetched_at'].replace(':', '')}.json").write_text(json.dumps(snap, indent=1))
    (d / "latest.json").write_text(json.dumps(snap, indent=1))
    return snap
