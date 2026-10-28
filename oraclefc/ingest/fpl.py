"""Fantasy Premier League public bootstrap (EPL injury / suspension flags, no key).

Allow-list only: names, team, status, chance of playing, news text and its timestamp.
Prices, ownership, transfers and "expected points" fields are never read.
"""
from __future__ import annotations

from .. import config
from ..governance import assert_no_market_keys
from .http import get_json

URL = "https://fantasy.premierleague.com/api/bootstrap-static/"
STATUS = {"a": "available", "d": "doubtful", "i": "injured", "s": "suspended", "u": "unavailable", "n": "not in squad"}


def availability(max_age_h: float = 1.0) -> list[dict]:
    d = get_json(URL, config.RAW_DIR / "fpl" / "bootstrap.json", max_age_h=max_age_h)
    if not d:
        return []
    teams = {t["id"]: t["name"] for t in d.get("teams", [])}
    out = []
    for e in d.get("elements", []):
        if e.get("status") == "a" and e.get("chance_of_playing_next_round") in (None, 100):
            continue
        out.append({"name": e.get("web_name"), "first_name": e.get("first_name"), "second_name": e.get("second_name"),
                    "team": teams.get(e.get("team")), "status": STATUS.get(e.get("status"), e.get("status")),
                    "chance_of_playing": e.get("chance_of_playing_next_round"), "news": e.get("news"),
                    "news_added": e.get("news_added")})
    assert_no_market_keys(out, "fpl availability")
    return out
