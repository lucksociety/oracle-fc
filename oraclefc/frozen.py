"""Immutable, timestamped forecast storage (Phase 8).

A forecast for (event, model version) is written exactly once with O_EXCL and a
SHA-256 of its canonical JSON. Later runs never overwrite it; the edge view
only uses forecasts whose ``frozen_at`` precedes the market snapshot.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from . import config
from .governance import assert_no_price_keys, now_utc_iso


class KickoffPassed(ValueError):
    """A new forecast was not complete before its scheduled kickoff."""


def _safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.+-]", "_", s)


def path_for(date: str, event_id: str, version: str) -> Path:
    return config.FORECAST_DIR / date / _safe(event_id) / f"{_safe(version)}.json"


def canonical_hash(obj: dict) -> str:
    body = {k: v for k, v in obj.items() if k not in ("sha256",)}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


def context_stage(forecast: dict) -> str:
    """Stage label + fingerprint of the information set. A new frozen record is written
    (never overwriting earlier ones) when lineups move from inferred -> projected ->
    confirmed or when the context moves the 1X2 probabilities by >= 0.5 pp."""
    c = forecast.get("context") or {}
    st = [((c.get("lineups") or {}).get(s) or {}).get("status", "none") for s in ("home", "away")]
    order = ["none", "inferred", "projected", "confirmed"]
    stage = min(st, key=lambda x: order.index(x) if x in order else 0)
    t = c.get("total_shift") or {}
    fp = tuple(round(2 * float(t.get(k, 0.0))) for k in ("d_p_home_pp", "d_p_draw_pp", "d_p_away_pp"))
    names = tuple(p.get("name") for s in ("home", "away") for p in ((c.get("lineups") or {}).get(s) or {}).get("starters", []))
    h = hashlib.sha256(json.dumps([st, fp, names, forecast.get("input_fingerprint"), forecast.get("resolved")]).encode()).hexdigest()[:8]
    return f"{stage}-{h}"


def freeze(date: str, event_id: str, version: str, forecast: dict) -> tuple[dict, bool]:
    """Write once per (event, model version, context stage). Returns (stored_forecast, newly_written)."""
    assert_no_price_keys(forecast, "frozen forecast")
    if forecast.get("context") is not None or forecast.get("input_fingerprint"):
        version = f"{version}__{context_stage(forecast)}"
    p = path_for(date, event_id, version)
    # A fit/context lookup can cross kickoff. Never publish a new snapshot afterwards.
    kickoff = (forecast.get("fixture") or {}).get("kickoff_utc")
    if kickoff and not p.exists():
        from datetime import datetime
        if datetime.fromisoformat(kickoff.replace("Z", "+00:00")) <= datetime.fromisoformat(now_utc_iso().replace("Z", "+00:00")):
            raise KickoffPassed("Cannot freeze a new forecast after kickoff")
    if p.exists():
        return json.loads(p.read_text()), False
    p.parent.mkdir(parents=True, exist_ok=True)
    rec = dict(forecast)
    rec["frozen_at"] = now_utc_iso()
    rec["sha256"] = canonical_hash(rec)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    with os.fdopen(fd, "w") as f:
        json.dump(rec, f, indent=1, default=str)
    with open(config.FORECAST_DIR / "ledger.jsonl", "a") as f:
        f.write(json.dumps({"frozen_at": rec["frozen_at"], "date": date, "event_id": event_id,
                            "version": version, "sha256": rec["sha256"]}) + "\n")
    return rec, True


def verify(rec: dict) -> bool:
    return rec.get("sha256") == canonical_hash(rec)


def load_date(date: str) -> list[dict]:
    d = config.FORECAST_DIR / date
    out = []
    if not d.exists():
        return out
    for ev_dir in sorted(d.iterdir()):
        files = sorted(ev_dir.glob("*.json"), key=lambda p: json.loads(p.read_text()).get("frozen_at", ""))
        if files:
            out.append(json.loads(files[-1].read_text()))
    return out
