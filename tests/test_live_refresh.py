import json
import pytest
from oraclefc import frozen,config
from oraclefc.ingest import http

def test_live_context_bypasses_recent_cache(tmp_path,monkeypatch):
    p=tmp_path/'fotmob'/'match'/'1.json';p.parent.mkdir(parents=True);p.write_text('{"starter":"old"}')
    calls=[]
    class Response:
        status_code=200
        def json(self): return {"starter":"new"}
    monkeypatch.setattr(http._S,'get',lambda *a,**k:(calls.append(k) or Response()))
    assert http.get_json('https://fixture.test',p,max_age_h=.5)=={'starter':'old'}
    monkeypatch.setenv('LIVE_REFRESH','1')
    assert http.get_json('https://fixture.test',p,max_age_h=.5)=={'starter':'new'}
    assert len(calls)==1 and calls[0]['headers']['Cache-Control']=='no-cache'

def test_every_refresh_keeps_new_immutable_snapshot(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'FORECAST_DIR',tmp_path)
    f={'fixture':{'kickoff_utc':'2099-01-01T00:00:00Z'},'context':{'lineups':{}},'model_version':'v1'}
    a,_=frozen.freeze('2099-01-01','game','v1',f,refresh_id='first')
    b,_=frozen.freeze('2099-01-01','game','v1',f,refresh_id='second')
    assert a['sha256']!=b['sha256'] and frozen.verify(a) and frozen.verify(b)
    assert len(list(tmp_path.rglob('*.json')))==2
    assert a['refresh_id']=='first'
    with pytest.raises(frozen.KickoffPassed):frozen.freeze('2000-01-01','past','v1',{'fixture':{'kickoff_utc':'2000-01-01T00:00:00Z'}},refresh_id='new')
