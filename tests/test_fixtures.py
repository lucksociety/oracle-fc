"""Fixture identity record: no market fields can ride along (discovery is tested in test_full_day_inventory)."""
import pytest

from oraclefc.fixtures.base import Fixture
from oraclefc.governance import is_prohibited_key


def test_fixture_has_identity_only():
    f = Fixture("POLY-1", "Chelsea FC", "Manchester United FC", "Premier League", "epl", "2026-11-01T15:00:00+00:00", "epl-che-mun-2026-11-01")
    d = f.to_dict()
    assert not [k for k in d if is_prohibited_key(k)]
    assert set(d) == {"event_id", "home_name", "away_name", "competition", "subcategory", "kickoff_utc", "slug", "source"}
    assert d["source"] == "polymarket-fixtures"


def test_fixture_rejects_extra_fields():
    with pytest.raises(TypeError):
        Fixture("POLY-1", "A", "B", "Premier League", "epl", "2026-11-01T15:00:00+00:00", "s", "polymarket-fixtures", 0.54)
