import pandas as pd
import pytest
from oraclefc import config,forecast
from oraclefc.resolve import Resolver
from oraclefc.ingest.espn_results import parse_results


def test_women_identities_cannot_resolve_to_mens_clubs(synthetic_matches):
    men=synthetic_matches.copy();men['home']=men['home'].replace({'T0':'Chelsea'});men['away']=men['away'].replace({'T0':'Chelsea'})
    women=men.copy();women['div']='WCL';women['country']='Women';women['home_key']='Women:'+women['home'];women['away_key']='Women:'+women['away']
    r=Resolver(pd.concat([men,women])).resolve('Chelsea FC','T1','uwcl')
    assert r.ok and r.home_key=='Women:Chelsea' and r.away_key=='Women:T1' and r.div=='WCL'
    assert not Resolver(men).resolve('Chelsea FC','T1','uwcl').ok


def test_women_forecasts_are_separate_and_forecast_only(synthetic_matches,monkeypatch):
    monkeypatch.setattr(forecast,'load_registry',lambda:{'champion':{'name':'dynamic_dc','version':'test','params':{'half_life_days':240,'kappa':8,'elo_k':22}}})
    women=synthetic_matches.copy();women['div']='WCL';women['country']='Women';women['home_key']='Women:'+women['home'];women['away_key']='Women:'+women['away']
    cutoff=women.date.max()+pd.Timedelta(days=1)
    engine=forecast.Engine(pd.concat([synthetic_matches,women]),as_of=cutoff,with_context=False)
    r=engine.forecast('T0','T1',"Women's Champions League",'uwcl',mc_sims=1000)
    assert r['status']=='ok' and r['forecast_only'] and r['model_version']=='supplemental-women-results-v1'
    assert set(engine.df['div'])=={'E0'}
    assert set(engine.supplemental_engines['women'].df['div'])=={'WCL'}
    assert 'men' not in engine.supplemental_engines
    with pytest.raises(ValueError,match='separate supplemental'):
        forecast.Engine(pd.concat([synthetic_matches,women]),as_of=cutoff,with_context=False,supplemental=True)


def test_women_results_keep_unique_namespace_and_regulation_only():
    event={'date':'2025-10-03T20:00Z','status':{'type':{'name':'STATUS_FULL_TIME'}},'competitions':[{'competitors':[
        {'homeAway':'home','team':{'id':'1','displayName':'Chelsea'},'score':'3'},
        {'homeAway':'away','team':{'id':'2','displayName':'Arsenal'},'score':'1'}]}]}
    row=list(parse_results({'events':[event]},'WCL',2025,'official'))[0]
    assert row['home_key']=='Women:espn-1' and row['home_key']!='England:espn-1'
    assert config.JUPITER_SUBCATEGORY_DIVS['uwcl']==sorted(config.WOMEN_DIVISIONS)
