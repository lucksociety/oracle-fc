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


def _safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.+-]", "_", s)


def path_for(date: str, event_id: str, version: str) -> Path:
    return config.FORECAST_DIR / date / _safe(event_id) / f"{_safe(version)}.json"


def canonical_hash(obj: dict) -> str:
    body = {k: v for k, v in obj.items() if k not in ("sha256",)}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


def freeze(date: str, event_id: str, version: str, forecast: dict) -> tuple[dict, bool]:
    """Write once. Returns (stored_forecast, newly_written)."""
    assert_no_price_keys(forecast, "frozen forecast")
    p = path_for(date, event_id, version)
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
