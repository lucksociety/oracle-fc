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
