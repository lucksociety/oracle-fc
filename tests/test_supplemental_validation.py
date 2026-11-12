import json
import numpy as np
from oraclefc import supplemental_validation as V


def record():
    return {'eligible':True,'tune_n':250,'test_n':250,'temperature':1.,'test_logloss':1.,'raw_model_logloss':1.,
            'exact_score_logloss':2.,'raw_exact_score_logloss':2.,'baseline_delta_week_bootstrap_99':{'ll':[-.1,-.01],'bs':[-.1,-.01]}}


def test_only_independently_supported_leagues_unlock():
    p={'leagues':{'COL':record()}}
    assert V.eligible(p,'COL');assert not V.eligible(p,'MEX2')
    for key,value in [('test_n',50),('eligible',False),('test_logloss',1.01),('temperature',.9)]:
        r=record();r[key]=value;assert not V.eligible({'leagues':{'COL':r}},'COL')
    r=record();r['baseline_delta_week_bootstrap_99']['ll'][1]=.01
    assert not V.eligible({'leagues':{'COL':r}},'COL')


def test_policy_never_uses_future_outcomes_or_mismatched_model_settings(tmp_path,monkeypatch):
    monkeypatch.setattr(V.config,'ROOT',tmp_path);(tmp_path/'experiments').mkdir()
    p={'schema':1,'model_params':{'kappa':8},'result_through':'2026-11-10','leagues':{'COL':record()}}
    (tmp_path/'experiments/supplemental-policy.json').write_text(json.dumps(p))
    assert not V.load_policy('2026-11-10',{'kappa':8})
    assert V.load_policy('2026-11-11',{'kappa':8})
    assert not V.load_policy('2026-11-11',{'kappa':6})


def test_joint_distribution_preserves_result_conditionals():
    m=np.array([[.1,.1,.05],[.1,.2,.05],[.1,.1,.2]])
    assert np.allclose(V.adjust(m,1.),m/m.sum())
    q=V.adjust(m,1.25);assert abs(q.sum()-1)<1e-12
    assert np.isclose(q[0,1]/q[0,2],m[0,1]/m[0,2])
    assert np.isfinite(q).all()and(q>=0).all()


def test_live_policy_clock_is_independent_of_stale_results_and_is_inherited(tmp_path,monkeypatch):
    import pandas as pd
    monkeypatch.setattr(V.config,'ROOT',tmp_path);(tmp_path/'experiments').mkdir()
    p={'schema':1,'model_params':{'kappa':8},'result_through':'2026-11-10','leagues':{'VEN':record()}}
    (tmp_path/'experiments/supplemental-policy.json').write_text(json.dumps(p))
    live=V.decision_time(now='2026-11-12T06:00:00Z')
    child=V.decision_time('2026-11-10',inherited=live)
    assert child==pd.Timestamp('2026-11-12T06:00:00')
    assert V.eligible(V.load_policy(child,{'kappa':8}),'VEN')
    historical=V.decision_time('2026-11-10',now='2026-11-12T06:00:00Z')
    assert not V.load_policy(historical,{'kappa':8})
    assert V.decision_time('2026-11-11T01:00:00+01:00')==pd.Timestamp('2026-11-11')


def test_engine_live_and_nested_policy_do_not_depend_on_latest_result(synthetic_matches,tmp_path,monkeypatch):
    import pandas as pd
    from oraclefc import forecast
    monkeypatch.setattr(V.config,'ROOT',tmp_path);(tmp_path/'experiments').mkdir()
    params={'half_life_days':240.,'kappa':8.,'elo_k':22.}
    monkeypatch.setattr(forecast,'load_registry',lambda:{'champion':{'name':'dynamic_dc','params':params}})
    p={'schema':1,'model_params':params,'result_through':'2026-11-10','leagues':{'VEN':record()}}
    (tmp_path/'experiments/supplemental-policy.json').write_text(json.dumps(p))
    clock=V.decision_time
    monkeypatch.setattr(V,'decision_time',lambda as_of=None,**kw:clock(as_of,**dict({'now':'2026-11-12T06:00:00Z'},**kw)))
    live=forecast.Engine(synthetic_matches,with_context=False,supplemental=True)
    nested=forecast.Engine(synthetic_matches,live.as_of,with_context=False,supplemental=True,validation_as_of=live.validation_as_of)
    historical=forecast.Engine(synthetic_matches,live.as_of,with_context=False,supplemental=True)
    assert live.as_of<pd.Timestamp('2026-11-10')
    assert V.eligible(live.supplemental_policy,'VEN')and V.eligible(nested.supplemental_policy,'VEN')
    assert not historical.supplemental_policy
    assert live.cutoff==historical.cutoff==nested.cutoff
