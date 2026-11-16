"""Fixture identity record shared by fixture sources.

Fixtures are discovered from Polymarket's public Gamma API (``fixtures.polymarket``) and
are used ONLY to learn which games exist on a date (teams, competition, kickoff). Every
event is copied through an explicit field allowlist — volume, prices, orderbooks and any
other market information are never copied, never stored and never reach a model.
(Prices live in ``oraclefc.market``, which model code is forbidden to import.)
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from .. import config
from ..governance import assert_no_market_keys

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
    source: str = "polymarket-fixtures"

    def to_dict(self) -> dict:
        d = asdict(self)
        assert_no_market_keys(d, "fixture")
        return d

    def local_date(self, tz: str = config.USER_TZ) -> str:
        return datetime.fromisoformat(self.kickoff_utc).astimezone(ZoneInfo(tz)).date().isoformat()


def fixtures_for_date(date: str, tz: str = config.USER_TZ, use_cache: bool = True) -> list[Fixture]:
    # Full-day inventory must include settled/started fixtures and unsupported men's leagues.
    from .polymarket import fixtures_for_date as full_day_fixtures
    return full_day_fixtures(date, tz=tz, use_cache=use_cache)
