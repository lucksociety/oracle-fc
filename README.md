<p align="center"><img src="web/assets/logo.jpg" width="96" alt="Luck Society"></p>

# ORACLE FC

**Independent football match simulation for [@lucksociety](https://x.com/lucksociety).**
Pick a date → ORACLE FC finds every soccer game listed on the **Jupiter prediction market** that day →
runs the full ORACLE FC forecast (exact score distribution, xG, 1X2, BTTS, totals, top-5 scores) for each →
freezes it → and only *afterwards* compares it with Jupiter prices on a separate **Edge (post-hoc)** tab.

> **Directive Zero.** Odds, market prices, implied probabilities and third-party predictions are **never**
> inputs, priors, calibration targets or weights. Jupiter is used for fixture *identity* only; prices live in a
> physically separate package (`oraclefc/market/`) that the forecasting code is forbidden to import (tested).

Live dashboard: **https://lucksociety.github.io/oracle-fc/** (rebuilt every 3 hours by GitHub Actions)

## Genuine walk-forward backtest (out of sample)

Test window 2023-07-01 → 2026-10-27, **40,327 matches** across 38 competitions (37 domestic divisions + UCL), weekly refits on data strictly
before each refit date. Full report: [`docs/BACKTEST.md`](docs/BACKTEST.md).

| Model | RPS ↓ | 1X2 log loss ↓ | Exact-score log score ↓ | Top-5 exact-score hit |
|---|---|---|---|---|
| League average (baseline) | 0.2328 | 1.0858 | 3.0078 | 47.7% |
| Home/away rate (baseline) | 0.2283 | 1.0733 | 2.9918 | 46.0% |
| Dixon–Coles (static) | 0.2138 | 1.0337 | 2.9582 | 48.0% |
| Goal-Elo | 0.2104 | 1.0220 | 2.9235 | 48.7% |
| Dynamic Dixon–Coles (frozen baseline) | 0.2103 | 1.0214 | 2.9197 | 49.1% |
| **Ensemble (champion)** | **0.2099** | **1.0201** | **2.9147** | **49.2%** |

The ensemble beat the frozen baseline with 95% block-bootstrap CIs entirely below zero
(ΔRPS −0.00040 [−0.00054, −0.00025]; Δexact log score −0.0051 [−0.0061, −0.0040]) and was promoted.
Calibration is good overall; the model is slightly *under*-confident on strong favourites
(P ≥ 0.60: predicted 67.8%, observed 70.6%) and slightly under-predicts total goals in several leagues —
see the weakness analysis in the backtest report.

## Quick start

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
python -m oraclefc.cli ingest                     # ~80 s: download + clean permitted results data
python -m oraclefc.cli backtest                   # ~15 min: tune, walk-forward, champion/challenger
python -m oraclefc.cli run --date 2026-10-31 --print   # forecast + freeze every Jupiter game that day
python -m oraclefc.cli edge --date 2026-10-31     # POST-HOC price comparison (after freezing)
python -m oraclefc.cli serve                      # dashboard at http://127.0.0.1:8000 (on-demand runs)
python -m pytest -q
```

Optional: `JUPITER_API_KEY` (env var / repo secret) raises Jupiter rate limits; the keyless API works.

## How it works

* **Data** (free, documented in [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md)): football-data.co.uk results for
  37 leagues (2016→today, odds columns stripped by allow-list) + openfootball Champions League results.
* **Models**: league average, home/away rate, Poisson, Dixon–Coles, time-weighted hierarchical *global*
  Dixon–Coles (one joint fit across all leagues + UCL), goal-based Elo, and an out-of-sample-weighted ensemble.
* **Simulation**: exact 11×11 joint score matrix (primary score = modal exact score, never rounded xG),
  Monte Carlo cross-check with convergence diagnostics, parameter-uncertainty intervals.
* **Governance**: allow/deny lists, schema validation, provenance with SHA-256, firewall tests,
  write-once frozen forecasts with a hash ledger, no forecasts after kickoff.
* **Team mapping**: Jupiter names → data names with aliases + conservative fuzzy matching; anything that
  cannot be matched is shown as **Not forecast** with the reason (never guessed).

Architecture: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) · Roadmap: [`docs/ROADMAP.md`](docs/ROADMAP.md)

## Known gaps (honest)

* No lineups, injuries, suspensions, weather or player data (no free point-in-time feed) — flagged in every report.
* Domestic cup results are not in the training data; Copa del Rey ties against Segunda/Tercera RFEF clubs, the
  Saudi Pro League, Qatar, Colombia, Turkey 1. Lig and Brazil Série B cannot be forecast yet.
* Champions League links come from openfootball 2016–2026; the 2026/27 UCL file isn't published yet, and
  Europa/Conference League use the UCL environment.
* Jupiter only lists active/upcoming events, so past dates show the frozen archive.

## Brand

Logo and banner are the public profile image and header of [@lucksociety](https://x.com/lucksociety)
(`web/assets/logo.jpg`, `web/assets/banner.jpg`). The palette (`web/assets/theme.css`) is extracted
programmatically by `scripts/extract_palette.py` (median-cut quantisation → role assignment by hue/lightness):
coin gold `#d69c08` / `#f9d731`, clover green `#026016`, Vegas-night teal `#011419` / `#031d20`, bronze `#b18423`.

*Research tool, not betting advice.*
