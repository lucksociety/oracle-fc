import pandas as pd
import requests
from oraclefc.ingest import http, understat


def test_expired_deadline_never_attempts_network(monkeypatch):
    monkeypatch.setattr(http._S,'get',lambda *a,**k:(_ for _ in ()).throw(AssertionError('network attempted')))
    assert http.get_json('https://unused.invalid',deadline=http.time.monotonic()-1) is None


def test_timeout_and_retry_sleep_share_deadline(monkeypatch):
    clock=[100.];calls=[]
    monkeypatch.setattr(http.time,'monotonic',lambda:clock[0])
    def fail(*a,**k):
        calls.append(k['timeout']);clock[0]+=k['timeout'];raise requests.Timeout('unavailable')
    monkeypatch.setattr(http._S,'get',fail)
    monkeypatch.setattr(http.time,'sleep',lambda s:clock.__setitem__(0,clock[0]+s))
    assert http.get_json('https://unused.invalid',timeout=30,retries=4,deadline=103) is None
    assert calls==[3] and clock[0]==103


def test_failed_refresh_keeps_existing_context(monkeypatch,tmp_path):
    monkeypatch.setattr(understat.config,'CONTEXT_DIR',tmp_path)
    m=pd.DataFrame({'us_id':[1],'is_result':[True]});p=pd.DataFrame({'us_id':[1],'player':['Known']})
    m.to_parquet(tmp_path/'understat_matches.parquet');p.to_parquet(tmp_path/'understat_players.parquet')
    before={x.name:x.read_bytes()for x in tmp_path.iterdir()}
    observed=[]
    def empty(*a,**k):observed.append(k['deadline']);return pd.DataFrame(columns=m.columns)
    monkeypatch.setattr(understat,'matches',empty)
    out=understat.update(max_seconds=60)
    assert out[0].equals(m) and out[1].equals(p) and observed[0] is not None
    assert before=={x.name:x.read_bytes()for x in tmp_path.iterdir()}


def test_bounded_refresh_never_starts_multiseason_bootstrap(monkeypatch,tmp_path):
    monkeypatch.setattr(understat.config,'CONTEXT_DIR',tmp_path)
    monkeypatch.setattr(understat,'build',lambda:(_ for _ in ()).throw(AssertionError('unbounded bootstrap')))
    assert understat.update(max_seconds=60) is None
