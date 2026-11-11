from datetime import datetime
import json
import pytest
import requests
from oraclefc.fixtures import polymarket as P
from oraclefc import forecast,frozen
from oraclefc.fixtures.jupiter import Fixture

def event(**changes):
    e={'id':'123','slug':'fif-vie-tpe-2026-11-11','title':'Vietnam vs. Chinese Taipei',
       'startTime':'2026-11-11T12:00:00Z','sport':{'sport':'fif','name':'FIFA Friendlies'},
       'tags':[{'slug':'soccer','label':'Soccer'}],
       'score':'untrusted','period':'CAN','ended':True,'closed':True,
       'markets':[{'prices':'never copy'}],'volume':999,'startDate':'2025-01-01T00:00:00Z'}
    return {**e,**changes}

def test_completed_unmodeled_mens_competition_is_discovered_without_market_fields():
    f=P.sanitise_event(event(),'2026-11-11');assert f.subcategory=='fif' and f.event_id=='POLY-123'
    assert f.source=='polymarket-fixtures'
    assert set(f.to_dict())=={'event_id','home_name','away_name','competition','subcategory','kickoff_utc','slug','source'}

def test_rescheduling_and_local_date_use_actual_kickoff_not_slug_or_creation_date():
    f=P.sanitise_event(event(slug='fif-vie-tpe-2026-11-14',startTime='2026-11-12T02:00:00Z'),'2026-11-11')
    assert f and f.local_date()=='2026-11-11'
    assert P.sanitise_event(event(startTime='2026-11-12T05:00:00Z'),'2026-11-11') is None
    assert P.sanitise_event(event(startTime='2026-11-11T04:59:59Z'),'2026-11-11') is None

@pytest.mark.parametrize('change',[
 {'slug':'fif-vie-tpe-2026-11-11-more-markets'}, {'slug':'fif-vie-tpe-2026-11-11-exact-score'},
 {'slug':'fif-vie-tpe-2026-11-11-halftime-result'}, {'slug':'fif-vie-tpe-2026-11-11-first-to-score'},
 {'slug':'fif-world-cup-winner'}, {'sport':{'sport':'uwcl','name':"Women's Champions League"}},
 {'tags':[{'slug':'soccer'},{'slug':'uwec'}]},
 {'title':'Vietnam Women vs. Chinese Taipei Women'},
 {'slug':'tpew-vie-tpe-2026-11-11','sport':{'sport':'tpew','name':'Taiwan Mulan Football League'}},
 {'startTime':None}, {'startTime':'2026-11-11T12:00:00'},
])
def test_props_women_outrights_and_invalid_dates_never_become_fixtures(change):
    assert P.sanitise_event(event(**change),'2026-11-11') is None

def test_open_closed_pagination_deduplication_and_cache(monkeypatch,tmp_path):
    calls=[]
    def get(params):
        calls.append(params)
        if params['closed']=='false':return [event(closed=False)]*100 if params['offset']==0 else [event(id='124')]
        return [event()]
    monkeypatch.setattr(P,'CACHE_DIR',tmp_path);monkeypatch.setattr(P,'_get',get)
    rows=P.fixtures_for_date('2026-11-11',use_cache=False)
    assert len(rows)==2 and len(calls)==3
    assert {x['closed'] for x in calls}=={'true','false'}
    assert calls[0]['start_time_min']=='2026-11-11T05:00:00+00:00'
    assert calls[0]['start_time_max']=='2026-11-12T05:00:00+00:00'
    assert len(P.fixtures_for_date('2026-11-11'))==2 and len(calls)==3
    assert 'prices' not in next(tmp_path.glob('*.json')).read_text()

def test_dst_day_is_25_hours_and_failures_do_not_cache_partial_inventory(monkeypatch,tmp_path):
    calls=[]
    def get(params):
        calls.append(params)
        if params['closed']=='true':raise requests.RequestException('closed page unavailable')
        return [event()]
    monkeypatch.setattr(P,'CACHE_DIR',tmp_path);monkeypatch.setattr(P,'_get',get)
    with pytest.raises(requests.RequestException):P.fixtures_for_date('2026-11-01',use_cache=False)
    hours=(datetime.fromisoformat(calls[0]['start_time_max'])-datetime.fromisoformat(calls[0]['start_time_min'])).total_seconds()/3600
    assert hours==25 and not list(tmp_path.glob('*.json'))

def test_past_discovered_game_never_calls_prediction_engine(monkeypatch):
    from oraclefc.fixtures import jupiter
    f=Fixture('POLY-1','Vietnam','Chinese Taipei','FIFA Friendlies','fif','2000-11-11T12:00:00+00:00','fif-vie-tpe-2000-11-11')
    monkeypatch.setattr(jupiter,'fixtures_for_date',lambda *a,**k:[f]);monkeypatch.setattr(frozen,'load_date',lambda _:[])
    class Engine:
        version='test';cutoff='2000-11-10'
        def forecast(self,*a,**k):raise AssertionError('post-kickoff prediction prohibited')
    r=forecast.forecast_date('2000-11-11',Engine(),freeze=False,use_cache=False)
    assert r['fixture_scope']=='full-day-men-v1' and r['n_fixtures']==1 and r['n_forecast']==0
    assert r['forecasts'][0]['status']=='not_forecast_before_kickoff'

def test_existing_pre_game_forecast_is_retained_for_earlier_game(monkeypatch):
    from oraclefc.fixtures import jupiter
    f=Fixture('POLY-1','Vietnam','Chinese Taipei','FIFA Friendlies','fif','2000-11-11T12:00:00+00:00','fif-vie-tpe-2000-11-11')
    saved={'status':'ok','fixture':f.to_dict(),'frozen_at':'2000-11-11T11:00:00+00:00','simulation':{'saved':True}}
    saved['sha256']=frozen.canonical_hash(saved)
    monkeypatch.setattr(jupiter,'fixtures_for_date',lambda *a,**k:[f]);monkeypatch.setattr(frozen,'load_date',lambda _:[saved])
    class Engine:
        version='test';cutoff='2000-11-10'
        def forecast(self,*a,**k):raise AssertionError('must retain old forecast')
    r=forecast.forecast_date('2000-11-11',Engine(),freeze=False)
    assert r['forecasts']==[saved] and frozen.verify(saved)

def test_unrated_mens_international_is_a_coverage_gap_not_a_gender_exclusion(synthetic_matches,monkeypatch):
    import pandas as pd
    monkeypatch.setattr(forecast,'load_registry',lambda:{'champion':{'name':'dynamic_dc','params':{'half_life_days':240,'kappa':8,'elo_k':22}}})
    e=forecast.Engine(synthetic_matches,as_of=synthetic_matches.date.max()+pd.Timedelta(days=1),with_context=False)
    result=e.forecast('Vietnam','Chinese Taipei','FIFA Friendlies','fif',mc_sims=1000)
    assert result['status']=='unsupported' and 'simulation' not in result
    assert result['fixture']['match_methods']['home']['method']=='unsupported-competition'

def test_rescheduled_or_delisted_saved_game_does_not_inflate_full_day_count(monkeypatch):
    from oraclefc.fixtures import jupiter
    old={'status':'ok','fixture':{'event_id':'POLY-old','subcategory':'epl','competition':'Premier League',
                                'home_name':'Home','away_name':'Away','kickoff_utc':'2000-11-11T12:00:00Z'}}
    monkeypatch.setattr(jupiter,'fixtures_for_date',lambda *a,**k:[])
    monkeypatch.setattr(frozen,'load_date',lambda _:[old])
    class Engine:version='test';cutoff='2000-11-10'
    r=forecast.forecast_date('2000-11-11',Engine(),freeze=False)
    assert r['n_fixtures']==0 and r['forecasts']==[] and old['status']=='ok'
