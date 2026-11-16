"""Fetch Polymarket prices for already-forecast events (public Gamma + CLOB APIs, no key).

    Gamma  GET  https://gamma-api.polymarket.com/events/{id}            match event (1X2 markets)
    Gamma  GET  https://gamma-api.polymarket.com/events?slug={slug}-more-markets | -exact-score
    CLOB   POST https://clob.polymarket.com/books  [{token_id}, ...]    executable order books

Every Gamma market is converted to one internal "event market" record per buyable contract
(``adapt_event``): ``pricing`` holds the best executable ask/bid in micro-USD taken from the
CLOB book of that outcome token, never the Gamma display price. Fees come from each market's
own ``feeSchedule``. Nothing here is imported by forecasting code (tests/test_firewall.py).
"""
from __future__ import annotations

import json
import re
import time

import requests

from .. import config
from ..governance import now_utc_iso
from .best_bet import selections_from_event

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
SIBLING_SUFFIXES = ("-more-markets", "-exact-score")
FULL_TIME_TYPES = {"moneyline", "both_teams_to_score", "totals", "soccer_team_totals", "spreads", "soccer_exact_score"}
GOALS_RE = re.compile(r"(\d+)\s+or more goals", re.IGNORECASE)
EXACT_RE = re.compile(r"^(?P<h>.+?)\s+(?P<hg>\d+)\s*-\s*(?P<ag>\d+)\s+(?P<a>.+)$")
TEAM_TOTAL_SIDE = re.compile(r"-team-total-(home|away)-")
HEADERS = {"User-Agent": "oracle-fc/1.0 (post-freeze price snapshot)"}


def _request(method, url, retries=5, **kw):
    for i in range(retries):
        try:
            r = requests.request(method, url, headers=HEADERS, timeout=30, **kw)
            if r.status_code == 429 or r.status_code >= 500:
                raise requests.HTTPError(f"{r.status_code} from {url}", response=r)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if i + 1 == retries or (status is not None and status != 429 and status < 500):
                raise
            time.sleep(min(20, 2 ** i))


def _list(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return []
    return value if isinstance(value, list) else []


def book_quote(book: dict | None) -> dict:
    """Best executable ask/bid of one outcome token (asks/bids arrive in no guaranteed order)."""
    def levels(side):
        out = []
        for x in (book or {}).get(side) or []:
            try:
                price, size = float(x["price"]), float(x["size"])
            except (KeyError, TypeError, ValueError):
                continue
            if 0 < price < 1 and size > 0:
                out.append((price, size))
        return out
    asks, bids = levels("asks"), levels("bids")
    ask = min((p for p, _ in asks), default=None)
    bid = max((p for p, _ in bids), default=None)
    depth = sum(n for p, n in asks if ask is not None and p <= ask + 1e-9)
    return {"ask": ask, "bid": bid, "ask_depth": depth, "timestamp": (book or {}).get("timestamp")}


def fetch_books(token_ids: list[str]) -> dict[str, dict]:
    out = {}
    for i in range(0, len(token_ids), 100):
        for b in _request("POST", f"{CLOB}/books", json=[{"token_id": t} for t in token_ids[i:i + 100]]) or []:
            out[str(b.get("asset_id"))] = book_quote(b)
    return out


def _usd(x):
    return int(round((x or 0) * 1e6))


def _fee(gm: dict) -> dict:
    """Per-market taker fee curve; an unknown schedule is charged the documented sports rate."""
    sched = gm.get("feeSchedule") or {}
    if gm.get("feesEnabled") is False:
        return {"rate": 0.0, "exponent": 1.0, "source": "market"}
    if "rate" in sched:
        return {"rate": float(sched["rate"]), "exponent": float(sched.get("exponent", 1)), "source": "market"}
    return {"rate": 0.05, "exponent": 1.0, "source": "assumed"}


def adapt_market(gm: dict, home: str, away: str, books: dict[str, dict]) -> list[dict]:
    """One Gamma market -> internal market records understood by ``selections_from_event``."""
    t = gm.get("sportsMarketType")
    if t not in FULL_TIME_TYPES or gm.get("closed") or gm.get("active") is False or gm.get("acceptingOrders") is False:
        return []
    outcomes, tokens = _list(gm.get("outcomes")), [str(x) for x in _list(gm.get("clobTokenIds"))]
    if len(outcomes) != 2 or len(tokens) != 2:
        return []
    q = [books.get(tok) or {} for tok in tokens]
    volume = gm.get("volumeNum")
    base = {"sportsMarketType": t, "status": "open", "provider": "polymarket", "rulesPrimary": gm.get("description") or "",
            "conditionId": gm.get("conditionId"), "slug": gm.get("slug"), "fee": _fee(gm)}
    line = gm.get("line")
    group = str(gm.get("groupItemTitle") or "").strip()
    slug = str(gm.get("slug") or "")
    if outcomes == ["Yes", "No"]:
        if t == "moneyline":
            title = "Draw" if slug.endswith("-draw") or group.lower().startswith("draw") else group
            if title not in ("Draw", home, away):
                return []
        elif t == "both_teams_to_score":
            title = "Both Teams to Score"
        elif t == "soccer_exact_score":
            title = group
        else:
            return []
        pricing = {"buyYesPriceUsd": _usd(q[0].get("ask")), "sellYesPriceUsd": _usd(q[0].get("bid")),
                   "buyNoPriceUsd": _usd(q[1].get("ask")), "sellNoPriceUsd": _usd(q[1].get("bid")),
                   "volume": volume, "askDepthYes": q[0].get("ask_depth"), "askDepthNo": q[1].get("ask_depth")}
        return [{**base, "marketId": f"POLY-{gm.get('id')}", "title": title, "isTeamMarket": False, "pricing": pricing}]
    out = []
    for i, label in enumerate(outcomes):
        m = {**base, "marketId": f"POLY-{gm.get('id')}-{i}", "title": str(label), "isTeamMarket": True,
             "pricing": {"buyYesPriceUsd": _usd(q[i].get("ask")), "sellYesPriceUsd": _usd(q[i].get("bid")),
                         "buyNoPriceUsd": 0, "sellNoPriceUsd": 0, "volume": volume, "askDepthYes": q[i].get("ask_depth")}}
        if t in ("totals", "soccer_team_totals"):
            if outcomes != ["Over", "Under"] or line is None:
                return []
            m["sportsLine"] = float(line)
            if t == "soccer_team_totals":
                side = TEAM_TOTAL_SIDE.search(slug)
                if not side:
                    return []
                m["team"] = {"name": home if side.group(1) == "home" else away}
        elif t == "spreads":
            # "Spread: Germany (-1.5)" with outcomes [Germany, Netherlands]: the line belongs to outcome 0.
            if line is None or set(outcomes) != {home, away}:
                return []
            hcp = float(line) if i == 0 else -float(line)
            m["team"] = {"name": str(label)}
            m["sportsLine"] = float(line)
            m["marketOptions"] = [{"label": f"{label} {hcp:+g}"}]
        else:
            return []
        out.append(m)
    return out


def adapt_event(events: list[dict], home: str, away: str, books: dict[str, dict]) -> dict:
    """Parent + sibling Gamma events of one match -> one internal event."""
    markets = []
    for ev in events:
        for gm in ev.get("markets") or []:
            markets.extend(adapt_market(gm, home, away, books))
    parent = events[0] if events else {}
    live = bool(parent.get("live") or parent.get("ended") or parent.get("closed"))
    return {"eventId": f"POLY-{parent.get('id')}", "isLive": live, "markets": markets}


def fetch_match_events(event_id: str, slug: str | None) -> list[dict]:
    gid = str(event_id).removeprefix("POLY-")
    parent = _request("GET", f"{GAMMA}/events/{gid}")
    if str(parent.get("id")) != gid or (slug and parent.get("slug") != slug):
        raise ValueError("event identity mismatch")
    events = [parent]
    for suffix in SIBLING_SUFFIXES:
        found = _request("GET", f"{GAMMA}/events", params={"slug": f"{parent.get('slug')}{suffix}"})
        events.extend(e for e in (found if isinstance(found, list) else []) if e.get("slug") == f"{parent.get('slug')}{suffix}")
    return events


def token_ids(events: list[dict]) -> list[str]:
    out = []
    for ev in events:
        for gm in ev.get("markets") or []:
            if gm.get("sportsMarketType") in FULL_TIME_TYPES and not gm.get("closed"):
                out.extend(str(x) for x in _list(gm.get("clobTokenIds")))
    return out


def _mid(pr: dict) -> dict:
    buy = (pr.get("buyYesPriceUsd") or 0) / 1e6
    sell = (pr.get("sellYesPriceUsd") or 0) / 1e6
    # Only quote a mid when there is a two-sided book with a sane spread.
    mid = (buy + sell) / 2 if (0 < sell <= buy < 1 and buy - sell <= 0.15) else None
    return {"ask": buy or None, "bid": sell or None, "mid": mid, "volume": pr.get("volume"),
            "spread": (buy - sell) if (buy and sell) else None}


def parse_event_markets(ev: dict, home: str, away: str) -> dict:
    out = {"moneyline": {}, "btts": None, "totals": {}, "exact": {}}
    for m in ev.get("markets") or []:
        t = m.get("sportsMarketType")
        title = (m.get("title") or "").strip()
        pr = _mid(m.get("pricing") or {})
        if m.get("periodType") or m.get("status") != "open":
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
    snap = {"fetched_at": now_utc_iso(), "date": date, "source": "polymarket gamma + clob", "events": {}}
    for eid in event_ids:
        fx = fixtures[eid]
        try:
            events = fetch_match_events(eid, fx.get("slug") or None)
            books = fetch_books(token_ids(events))
            ev = adapt_event(events, fx["home_name"], fx["away_name"], books)
        except Exception as e:  # noqa: BLE001
            snap["events"][eid] = {"error": str(e)}
            continue
        if ev.get("eventId") != eid or ev.get("isLive"):
            snap["events"][eid] = {"error": "event identity mismatch or market already live"}
            continue
        received_at = now_utc_iso()
        snap["events"][eid] = parse_event_markets(ev, fx["home_name"], fx["away_name"])
        snap["events"][eid]["selections"] = selections_from_event(ev, fx["home_name"], fx["away_name"])
        snap["events"][eid]["fetched_at"] = received_at
        time.sleep(0.1)
    snap["fetched_at"] = now_utc_iso()
    d = config.MARKET_DIR / date
    d.mkdir(parents=True, exist_ok=True)
    (d / f"snapshot_{snap['fetched_at'].replace(':', '')}.json").write_text(json.dumps(snap, indent=1))
    (d / "latest.json").write_text(json.dumps(snap, indent=1))
    return snap
