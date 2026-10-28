from oraclefc.fixtures.jupiter import sanitise_event
from oraclefc.governance import is_prohibited_key

EVENT = {"eventId": "POLY-1", "subcategory": "epl", "tags": ["soccer"], "beginAt": "1793450000",
         "volumeUsd": 12345, "volume24hr": 99,
         "metadata": {"title": "Chelsea FC vs. Manchester United FC", "league": "Premier League", "slug": "epl-x"},
         "markets": [{"title": "Chelsea FC", "pricing": {"buyYesPriceUsd": 540000}}]}


def test_sanitised_fixture_has_identity_only():
    f = sanitise_event(EVENT)
    d = f.to_dict()
    assert d["home_name"] == "Chelsea FC" and d["away_name"] == "Manchester United FC"
    assert not [k for k in d if is_prohibited_key(k)]
    assert "markets" not in d and "volumeUsd" not in d
    assert set(d) == {"event_id", "home_name", "away_name", "competition", "subcategory", "kickoff_utc",
                      "slug", "source"}


def test_outrights_are_not_fixtures():
    ev = dict(EVENT, metadata={"title": "EPL: 2027 Champion"})
    assert sanitise_event(ev) is None
