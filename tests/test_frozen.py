import os

from oraclefc import config, frozen


def test_freeze_is_write_once(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "FORECAST_DIR", tmp_path)
    fc = {"fixture": {"event_id": "E1"}, "simulation": {"p_home": 0.5}, "status": "ok"}
    a, new = frozen.freeze("2026-10-28", "E1", "v1", fc)
    assert new and frozen.verify(a)
    b, new2 = frozen.freeze("2026-10-28", "E1", "v1", dict(fc, simulation={"p_home": 0.9}))
    assert not new2 and b["simulation"]["p_home"] == 0.5 and b["frozen_at"] == a["frozen_at"]
    p = frozen.path_for("2026-10-28", "E1", "v1")
    assert not os.access(p, os.W_OK) or os.geteuid() == 0
    b["simulation"]["p_home"] = 0.9
    assert not frozen.verify(b)  # tampering is detectable


def test_changed_training_inputs_append_a_new_snapshot_without_overwriting(tmp_path, monkeypatch):
    monkeypatch.setattr(config,'FORECAST_DIR',tmp_path)
    stamp=iter(['2026-10-31T10:00:00+00:00','2026-10-31T11:00:00+00:00'])
    monkeypatch.setattr(frozen,'now_utc_iso',lambda:next(stamp))
    fc={'fixture':{'event_id':'E1'},'status':'ok','simulation':{'p_home':.5},
        'input_fingerprint':'old-inputs','resolved':{'away_key':'Spain:Barcelona'}}
    a,new=frozen.freeze('2026-11-01','E1','v1',fc)
    b,newer=frozen.freeze('2026-11-01','E1','v1',{**fc,'input_fingerprint':'corrected-inputs',
        'resolved':{'away_key':'Spain:Espanol'},'simulation':{'p_home':.7}})
    assert new and newer and frozen.verify(a) and frozen.verify(b)
    assert len(list((tmp_path/'2026-11-01'/'E1').glob('*.json')))==2
    assert frozen.load_date('2026-11-01')[0]['input_fingerprint']=='corrected-inputs'
    assert a['simulation']['p_home']==.5


def test_fit_that_finishes_after_kickoff_cannot_publish(tmp_path,monkeypatch):
    import pytest
    monkeypatch.setattr(config,'FORECAST_DIR',tmp_path)
    monkeypatch.setattr(frozen,'now_utc_iso',lambda:'2026-10-31T20:01:00+00:00')
    fc={'fixture':{'kickoff_utc':'2026-10-31T20:00:00+00:00'},'status':'ok','input_fingerprint':'x'}
    with pytest.raises(ValueError,match='after kickoff'):
        frozen.freeze('2026-10-31','E1','v1',fc)
