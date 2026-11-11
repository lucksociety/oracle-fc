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


def test_non_polymarket_events_are_excluded():
    assert sanitise_event(dict(EVENT, eventId="KALSHI-1")) is None

def test_transient_page_error_is_retried(monkeypatch):
    import requests
    from oraclefc.fixtures import jupiter
    calls=[]
    class Response:
        def __init__(self,status):self.status_code=status
        def raise_for_status(self):
            if self.status_code>=400:raise requests.HTTPError(response=self)
        def json(self):return {'data':[]}
    def get(*a,**k):calls.append(k);return Response(500 if len(calls)==1 else 200)
    monkeypatch.setattr(jupiter.requests,'get',get);monkeypatch.setattr(jupiter.time,'sleep',lambda _:None)
    assert jupiter._get('url',{})=={'data':[]} and len(calls)==2

def test_discovery_only_walks_upcoming_pages_and_never_returns_women(tmp_path,monkeypatch):
    from oraclefc.fixtures import jupiter
    seen=[]
    def get(url,params):
        seen.append(params)
        return {'data':[EVENT,{**EVENT,'eventId':'POLY-w','subcategory':'uwcl'}],'pagination':{'hasNext':False}}
    monkeypatch.setattr(jupiter,'CACHE',tmp_path/'fixtures.json');monkeypatch.setattr(jupiter,'_get',get)
    rows=jupiter.fetch_all_soccer(False)
    assert seen[0]['filter']=='upcoming' and [r.event_id for r in rows]==['POLY-1']

def test_date_bounded_discovery_stops_after_sorted_next_day_and_cache_scope_is_respected(tmp_path,monkeypatch):
    import datetime
    from oraclefc.fixtures import jupiter
    calls=[]
    def get(url,params):
        calls.append(params)
        day='2026-11-12' if len(calls)==1 else '2026-11-13'
        stamp=str(int(datetime.datetime.fromisoformat(day+'T12:00:00+00:00').timestamp()))
        return {'data':[{**EVENT,'beginAt':stamp}],'pagination':{'hasNext':True}}
    monkeypatch.setattr(jupiter,'CACHE',tmp_path/'cache.json');monkeypatch.setattr(jupiter,'_get',get)
    jupiter.fetch_all_soccer(False,through_date='2026-11-11');assert len(calls)==1
    jupiter.fetch_all_soccer(True,through_date='2026-11-11');assert len(calls)==1
    jupiter.fetch_all_soccer(True,through_date='2026-11-12');assert len(calls)==2
