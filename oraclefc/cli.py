"""ORACLE FC command line.

  python -m oraclefc.cli ingest                 # download + clean permitted data
  python -m oraclefc.cli backtest [--skip-tune]  # walk-forward validation, champion/challenger
  python -m oraclefc.cli run [--date D] [--days N]   # discover Jupiter fixtures, forecast, freeze
  python -m oraclefc.cli edge [--date D]         # POST-HOC: snapshot market prices, compare to frozen forecasts
  python -m oraclefc.cli grade [--date D] [--days N]  # POST-MATCH: grade forecasts + bets vs results
  python -m oraclefc.cli predict HOME AWAY --comp epl
  python -m oraclefc.cli serve                   # FastAPI dashboard on :8000
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import config


def _today() -> str:
    return datetime.now(ZoneInfo(config.USER_TZ)).date().isoformat()


def _dates(date: str | None, days: int) -> list[str]:
    d0 = datetime.fromisoformat(date or _today()).date()
    return [(d0 + timedelta(days=i)).isoformat() for i in range(days)]


def cmd_ingest(a):
    from . import store
    df = store.build()
    print(f"clean matches: {len(df):,}; cutoff {store.data_cutoff(df)}")


def cmd_ingest_context(a):
    """Refresh the committed Understat snapshot (current season). FotMob/FPL/Open-Meteo are
    fetched live at forecast time. Failures are non-fatal: forecasts fall back to team level."""
    from .ingest import understat
    try:
        understat.update()
    except Exception as e:  # noqa: BLE001
        print(f"understat update failed (non-fatal): {e}")


def cmd_backtest(a):
    from . import run_backtest
    run_backtest.main(skip_tune=a.skip_tune)


def cmd_run(a):
    from .forecast import Engine, forecast_date
    out_dir = config.DATA_DIR / "dates"
    out_dir.mkdir(parents=True, exist_ok=True)
    eng = Engine()
    for d in _dates(a.date, a.days):
        res = forecast_date(d, eng, freeze=not a.no_freeze, use_cache=not a.refresh, within_hours=a.within_hours)
        (out_dir / f"{d}.json").write_text(json.dumps(res, default=str))
        print(f"{d}: {res['n_fixtures']} Jupiter fixtures, {res['n_forecast']} forecast")
        if a.print:
            for f in res["forecasts"]:
                if f.get("status") == "ok":
                    print(f["report_text"])


def cmd_edge(a):
    from .market.edge import edge_for_date
    out_dir = config.DATA_DIR / "edge"
    out_dir.mkdir(parents=True, exist_ok=True)
    for d in _dates(a.date, a.days):
        res = edge_for_date(d)
        (out_dir / f"{d}.json").write_text(json.dumps(res, default=str))
        print(f"{d}: post-hoc edge for {len(res['events'])} events")


def cmd_grade(a):
    """POST-MATCH: grade frozen forecasts + best bets against final 90-minute scores."""
    from .market import grade
    if a.date:
        dates = _dates(a.date, a.days)
    else:  # default: the last N days before today (their games are finished)
        d0 = datetime.fromisoformat(_today()).date()
        dates = [(d0 - timedelta(days=i)).isoformat() for i in range(a.days, 0, -1)]
    for d in dates:
        if not (config.FORECAST_DIR / d).exists():
            continue
        res = grade.grade_date(d)
        grade.write(d, res)
        s = res["summary"]
        b = s["bets"]
        print(f"{d}: {s['n_final']}/{s['n_games']} final, bets {b['wins']}-{b['losses']} ({b['units']:+.2f}u)")


def cmd_predict(a):
    from .forecast import Engine
    fc = Engine().forecast(a.home, a.away, competition=a.comp, subcategory=a.comp)
    print(fc.get("report_text") or json.dumps(fc, indent=1, default=str))


def cmd_serve(a):
    import uvicorn
    uvicorn.run("oraclefc.api:app", host=a.host, port=a.port)


def main(argv=None):
    p = argparse.ArgumentParser(prog="oraclefc")
    sp = p.add_subparsers(dest="cmd", required=True)
    sp.add_parser("ingest").set_defaults(f=cmd_ingest)
    b = sp.add_parser("backtest"); b.add_argument("--skip-tune", action="store_true"); b.set_defaults(f=cmd_backtest)
    r = sp.add_parser("run")
    r.add_argument("--date"); r.add_argument("--days", type=int, default=1)
    r.add_argument("--no-freeze", action="store_true"); r.add_argument("--refresh", action="store_true")
    r.add_argument("--within-hours", type=float, default=None,
                   help="only re-forecast fixtures kicking off within N hours (others reuse their frozen forecast)")
    r.add_argument("--print", action="store_true"); r.set_defaults(f=cmd_run)
    sp.add_parser("ingest-context").set_defaults(f=cmd_ingest_context)
    e = sp.add_parser("edge"); e.add_argument("--date"); e.add_argument("--days", type=int, default=1)
    e.set_defaults(f=cmd_edge)
    g = sp.add_parser("grade"); g.add_argument("--date"); g.add_argument("--days", type=int, default=2)
    g.set_defaults(f=cmd_grade)
    pr = sp.add_parser("predict"); pr.add_argument("home"); pr.add_argument("away")
    pr.add_argument("--comp", default="epl"); pr.set_defaults(f=cmd_predict)
    s = sp.add_parser("serve"); s.add_argument("--host", default="127.0.0.1"); s.add_argument("--port", type=int, default=8000)
    s.set_defaults(f=cmd_serve)
    a = p.parse_args(argv)
    a.f(a)


if __name__ == "__main__":
    main()
