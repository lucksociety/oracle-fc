"""Women's events must never enter training, discovery, forecasts or fallback output."""
import pandas as pd
from oraclefc import forecast,config
from oraclefc.sports_policy import allowed
from oraclefc.ingest.espn_results import parse_results
from oraclefc.fixtures.polymarket import sanitise_event

def test_mens_only_configuration():
    assert not set(config.SUPPLEMENTAL_DIVISIONS)&config.WOMEN_DIVISIONS
    assert all('women' not in v.lower() for v in config.SUPPLEMENTAL_FEEDS.values())
    assert not allowed('uwcl',"Women's Champions League")
    assert not allowed('uwec',"UEFA Women's Europa Cup")
    assert not allowed('epl',"Women's Premier League")
    assert allowed('epl','Premier League')

def test_women_excluded_from_engine_training_and_manual_forecast(synthetic_matches,monkeypatch):
    monkeypatch.setattr(forecast,'load_registry',lambda:{'champion':{'name':'dynamic_dc','params':{'half_life_days':240,'kappa':8,'elo_k':22}}})
    women=synthetic_matches.copy();women['div']='WCL';women['country']='Women';women['hg']=99
    engine=forecast.Engine(pd.concat([synthetic_matches,women]),as_of=synthetic_matches.date.max()+pd.Timedelta(days=1),with_context=False)
    assert set(engine.df['div'])=={'E0'}
    r=engine.forecast('T0','T1',"Women's Champions League",'uwcl',mc_sims=1000)
    assert r['status']=='excluded' and 'simulation' not in r

def test_women_discovery_and_results_rejected():
    raw={'id':'1','slug':'uwcl-che-ars-2026-11-11','title':'Chelsea vs. Arsenal','startTime':'2026-11-11T19:00:00Z',
         'sport':{'sport':'uwcl','name':"Women's Champions League"},'tags':[{'slug':'soccer','label':'Soccer'}]}
    assert sanitise_event(raw,'2026-11-11') is None
    assert list(parse_results({'events':[]},'WCL',2026,'source'))==[]
