import pandas as pd
import numpy as np
from oraclefc import forecast


def test_engine_resolver_metadata_and_fingerprint_obey_fit_cutoff(synthetic_matches,monkeypatch):
    monkeypatch.setattr(forecast,'load_registry',lambda:{'champion':{'name':'dynamic_dc','version':'test',
        'params':{'half_life_days':240,'kappa':8,'elo_k':22}}})
    cutoff=pd.Timestamp('2022-03-01')
    a=forecast.Engine(synthetic_matches,as_of=cutoff,with_context=False)
    poisoned=synthetic_matches.copy()
    poisoned.loc[poisoned.date>=cutoff,'hg']=999
    b=forecast.Engine(poisoned,as_of=cutoff,with_context=False)
    assert a.input_fingerprint==b.input_fingerprint
    assert a.df.date.max()<cutoff and a.resolver.df.date.max()<cutoff
    changed=synthetic_matches.copy();changed.loc[changed.date<cutoff,'hg']+=1
    c=forecast.Engine(changed,as_of=cutoff,with_context=False)
    assert c.input_fingerprint!=a.input_fingerprint
    fx=a.resolver.fixture_frame(a.resolver.resolve('T0','T1','epl'))
    np.testing.assert_allclose(a.matrix(fx)[0],b.matrix(fx)[0])


def test_player_context_book_excludes_future_understat_rows(synthetic_matches,monkeypatch):
    from oraclefc.context import history
    monkeypatch.setattr(forecast,'load_registry',lambda:{'champion':{'name':'dynamic_dc','version':'test',
        'params':{'half_life_days':240,'kappa':8,'elo_k':22}}})
    records=pd.DataFrame({'datetime':pd.to_datetime(['2021-01-01','2030-01-01'])})
    monkeypatch.setattr(history,'map_understat',lambda df:records)
    seen=[]
    def book(df):
        seen.append(df.datetime.max())
        return pd.DataFrame(),None
    monkeypatch.setattr(history,'lineup_history',book)
    forecast.Engine(synthetic_matches,as_of=pd.Timestamp('2022-03-01'),with_context=True)
    assert seen==[pd.Timestamp('2021-01-01')]
