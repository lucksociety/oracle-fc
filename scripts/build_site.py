"""Assemble the static GitHub Pages site into ./site from web/ + pipeline outputs."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from oraclefc import config  # noqa: E402
from oraclefc.experiments import load_registry  # noqa: E402

SITE = ROOT / "site"


def main():
    if SITE.exists():
        shutil.rmtree(SITE)
    shutil.copytree(ROOT / "web", SITE)
    data = SITE / "data"
    for sub in ("dates", "edge"):
        src = config.DATA_DIR / sub
        (data / sub).mkdir(parents=True, exist_ok=True)
        if src.exists():
            for f in src.glob("*.json"):
                shutil.copy(f, data / sub / f.name)
    # past dates no longer listed by Jupiter: rebuild the date view from frozen forecasts
    from oraclefc import frozen
    if config.FORECAST_DIR.exists():
        for d in sorted(p.name for p in config.FORECAST_DIR.iterdir() if p.is_dir()):
            out = data / "dates" / f"{d}.json"
            if out.exists():
                continue
            fcs = frozen.load_date(d)
            out.write_text(json.dumps({"date": d, "tz": config.USER_TZ, "from_frozen_archive": True,
                                       "n_fixtures": len(fcs), "n_forecast": len(fcs),
                                       "model_version": fcs[0]["model_version"] if fcs else None,
                                       "data_cutoff": fcs[0]["data_cutoff"] if fcs else None,
                                       "forecasts": sorted(fcs, key=lambda x: x["fixture"].get("kickoff_utc") or "")},
                                      default=str))
    summ = config.BACKTEST_DIR / "latest_summary.json"
    cs = config.BACKTEST_DIR / "context_summary.json"
    model = {"registry": load_registry(), "backtest": json.loads(summ.read_text()) if summ.exists() else None,
             "context": json.loads(cs.read_text()) if cs.exists() else None}
    (data / "model.json").write_text(json.dumps(model, default=str))
    dates = sorted(p.stem for p in (data / "dates").glob("*.json"))
    (data / "index.json").write_text(json.dumps({"dates": dates}))
    (SITE / ".nojekyll").write_text("")
    print(f"site built: {len(dates)} dates")


if __name__ == "__main__":
    main()
