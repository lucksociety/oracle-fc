"""FastAPI dashboard backend (local / self-hosted mode).

Forecast endpoints never touch oraclefc.market. The /api/edge endpoint is the
only place prices appear, and it reads already-frozen forecasts.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .experiments import load_registry

app = FastAPI(title="ORACLE FC", version="1.0")
_engine = None
_lock = threading.Lock()
WEB = config.ROOT / "web"


def engine():
    global _engine
    with _lock:
        if _engine is None:
            from .forecast import Engine
            _engine = Engine()
        return _engine


def _check_date(date: str) -> str:
    try:
        return datetime.fromisoformat(date).date().isoformat()
    except ValueError as e:
        raise HTTPException(400, "date must be YYYY-MM-DD") from e


@app.get("/api/health")
def health():
    return {"ok": True, "mode": "api"}


@app.get("/api/fixtures")
def fixtures(date: str = Query(...)):
    from .fixtures.jupiter import fixtures_for_date
    return {"date": _check_date(date), "fixtures": [f.to_dict() for f in fixtures_for_date(date)]}


@app.get("/api/forecasts")
def forecasts(date: str = Query(...), refresh: bool = False):
    from .forecast import forecast_date
    d = _check_date(date)
    res = forecast_date(d, engine(), freeze=True, use_cache=not refresh)
    out = config.DATA_DIR / "dates"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{d}.json").write_text(json.dumps(res, default=str))
    return json.loads(json.dumps(res, default=str))


@app.get("/api/predict")
def predict(home: str, away: str, comp: str = "epl"):
    fc = engine().forecast(home, away, competition=comp, subcategory=comp)
    return json.loads(json.dumps(fc, default=str))


@app.get("/api/edge")
def edge(date: str = Query(...)):
    from .market.edge import edge_for_date  # post-hoc only
    return json.loads(json.dumps(edge_for_date(_check_date(date)), default=str))


@app.get("/api/model")
def model():
    reg = load_registry()
    p = config.BACKTEST_DIR / "latest_summary.json"
    summ = json.loads(p.read_text()) if p.exists() else None
    cp = config.BACKTEST_DIR / "context_summary.json"
    return {"registry": reg, "backtest": summ, "context": json.loads(cp.read_text()) if cp.exists() else None,
            "today": datetime.now(ZoneInfo(config.USER_TZ)).date().isoformat()}


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


app.mount("/", StaticFiles(directory=WEB), name="web")
