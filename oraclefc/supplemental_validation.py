"""Point-in-time eligibility of results-only leagues, independently of market prices."""
import json,math
from pathlib import Path
import numpy as np
import pandas as pd
from . import config


def decision_time(as_of=None,*,inherited=None,now=None):
    """Live policy knowledge is independent of the last ingested result date.

    Explicit historical cutoffs remain point-in-time; nested supplemental models
    inherit the parent's decision time, not its stale training cutoff.
    """
    value=inherited if inherited is not None else as_of if as_of is not None else now if now is not None else pd.Timestamp.now(tz='UTC')
    stamp=pd.Timestamp(value)
    return stamp.tz_convert('UTC').tz_localize(None) if stamp.tzinfo is not None else stamp


def load_policy(as_of,params):
    path=config.ROOT/'experiments/supplemental-policy.json'
    if not path.exists():return {}
    policy=json.loads(path.read_text())
    if policy.get('schema')!=1 or policy.get('model_params')!=params:return {}
    # Every evaluation outcome must have been available before this forecast.
    if pd.Timestamp(policy['result_through'])+pd.Timedelta(days=1)>decision_time(as_of):return {}
    return policy


def eligible(policy,division):
    r=policy.get('leagues',{}).get(str(division),{})
    intervals=r.get('baseline_delta_week_bootstrap_99',{})
    return bool(r.get('eligible')is True and r.get('tune_n',0)>=200 and r.get('test_n',0)>=200
                and all(len(intervals.get(k,[]))==2 and intervals[k][1]<0 for k in ['ll','bs'])
                and r.get('test_logloss',math.inf)<=r.get('raw_model_logloss',-math.inf)+1e-12
                and r.get('exact_score_logloss',math.inf)<=r.get('raw_exact_score_logloss',-math.inf)+1e-12
                and 1<=r.get('temperature',0)<=2)


def adjust(matrix,temperature):
    m=np.asarray(matrix,float);h,a=np.indices(m.shape);masks=[h>a,h==a,h<a]
    p=np.array([m[mask].sum()for mask in masks]);q=p**(1/temperature);q/=q.sum()
    result=m.copy()
    for mask,old,new in zip(masks,p,q):
        if old>0:result[mask]*=new/old
    return result/result.sum()
