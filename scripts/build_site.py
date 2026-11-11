"""Assemble the static GitHub Pages site into ./site from web/ + pipeline outputs."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from oraclefc.sports_policy import fixture_allowed, WOMEN
from oraclefc import config  # noqa: E402
from oraclefc.experiments import load_registry  # noqa: E402

SITE = ROOT / "site"


def main():
    if SITE.exists():
        shutil.rmtree(SITE)
    shutil.copytree(ROOT / "web", SITE)
    data = SITE / "data"
    for sub in ("dates", "edge", "results"):
        src = config.DATA_DIR / sub
        (data / sub).mkdir(parents=True, exist_ok=True)
        if src.exists():
            for f in src.glob("*.json"):
                obj=json.loads(f.read_text())
                if sub=='dates':
                    obj['forecasts']=[r for r in obj.get('forecasts',[]) if fixture_allowed(r.get('fixture',{}))]
                    obj['n_fixtures']=len(obj['forecasts']);obj['n_forecast']=sum(r.get('status')=='ok' for r in obj['forecasts'])
                if sub=='edge':
                    obj['events']=[r for r in obj.get('events',[]) if not WOMEN.search(str(r.get('competition','')))]
                    bb=obj.get('best_bets') or {}
                    if 'games' in bb:bb['games']=[r for r in bb['games'] if not WOMEN.search(str(r.get('competition','')))]
                (data / sub / f.name).write_text(json.dumps(obj,default=str))
    # past dates no longer listed by Jupiter: rebuild the date view from frozen forecasts
    from oraclefc import frozen
    if config.FORECAST_DIR.exists():
        for d in sorted(p.name for p in config.FORECAST_DIR.iterdir() if p.is_dir()):
            out = data / "dates" / f"{d}.json"
            if out.exists():
                continue
            fcs = [f for f in frozen.load_date(d) if fixture_allowed(f.get("fixture",{}))]
            out.write_text(json.dumps({"date": d, "tz": config.USER_TZ, "from_frozen_archive": True,
                                       "n_fixtures": len(fcs), "n_forecast": len(fcs),
                                       "model_version": fcs[0]["model_version"] if fcs else None,
                                       "data_cutoff": fcs[0]["data_cutoff"] if fcs else None,
                                       "forecasts": sorted(fcs, key=lambda x: x["fixture"].get("kickoff_utc") or "")},
                                      default=str))
    summ = config.BACKTEST_DIR / "latest_summary.json"
    cs = config.BACKTEST_DIR / "context_summary.json"
    cal = config.BACKTEST_DIR / "calibration_summary.json"
    cal_js = None
    if cal.exists():
        c = json.loads(cal.read_text())
        cal_js = {k: c.get(k) for k in ("experiment_id", "test_window", "n_test", "base", "chosen", "production")}
        cal_js["variants"] = {n: {"summary": v["summary"], "delta": v["delta"], "eligible": v["eligible"]}
                              for n, v in (c.get("variants") or {}).items()}
    model = {"registry": load_registry(), "backtest": json.loads(summ.read_text()) if summ.exists() else None,
             "context": json.loads(cs.read_text()) if cs.exists() else None, "calibration": cal_js}
    (data / "model.json").write_text(json.dumps(model, default=str))
    dates = sorted(p.stem for p in (data / "dates").glob("*.json"))
    (data / "index.json").write_text(json.dumps({"dates": dates}))
    (SITE / ".nojekyll").write_text("")
    print(f"site built: {len(dates)} dates")


if __name__ == "__main__":
    main()
