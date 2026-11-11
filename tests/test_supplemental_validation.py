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
