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

### Calibration layer (v1.2.0)

On top of the ensemble, `oraclefc/calibrate.py` reshapes each score matrix as Q ∝ P^(1+t)·exp(dh·h + da·a + dd·1[draw] + d0·1[0-0]), fitted by maximum likelihood on walk-forward **out-of-sample** matrices and **results only** (`python -m oraclefc.run_calibration`, weekly in the backtest workflow; season-ahead nested in the backtest). Adopted variant `global+sharpen`: about +4.7% home and away goals, a small draw lift (+5.6% relative) and slight sharpening (t = 0.06). Over 2023-07-01 → 2026-10-28 (n = 40,603): ΔRPS −0.00008 [−0.00014, −0.00002], Δ1X2 log loss −0.00058 [−0.00082, −0.00033], Δexact-score log score −0.00106 [−0.00156, −0.00052]. Why it was needed: the base ensemble **over-stated unders and BTTS-No by 1–3 pp** in exactly the probability bands the best-bet rule trades, and slightly under-stated draws. Per-division variants overfit and were rejected. See [docs/CALIBRATION.md](docs/CALIBRATION.md).

## Best Bets (post-hoc, after freezing)

For every game the Edge layer (`oraclefc/market/best_bet.py`, mirrored in `web/bestbet.js`) prices every **buyable** Jupiter side we can model from the frozen score grid — 1X2 (YES and NO), BTTS, match totals, team totals, spreads, exact score — and picks **one** best bet:

* **Eligible** only if model P > 50% **and** EV > 0 buying at the Jupiter **ask** (not mid).
* **EV per $1** = P / (ask + fee) − 1. Fee per contract = Jupiter builder fee 2%·ask + Polymarket sports taker fee 0.05·ask·(1−ask) ([Jupiter fees](https://docs.jup.ag/user-docs/trade/predict/fees), [Polymarket fees](https://docs.polymarket.com/trading/fees), market `feeSchedule` `sports_fees_v3`, checked 2026-10-28). Jupiter rounds each order's fee up to the cent, so tiny orders cost slightly more.
* Highest EV wins; otherwise **NO BET** (with the closest miss shown). Prices fetched after kick-off, or forecasts frozen after the snapshot, are always NO BET.
* Shown as a banner on every game card and as a **Best Bets** table per date. Half-time, corners and first-to-score markets are not modelled and never selected.
* There is no backtest of betting returns (Directive Zero forbids historical odds), so these are research flags, not advice.
* **Locking.** The lineups job re-prices every 20 min; once a game kicks off, its last **pre-kick-off** verdict is kept (`locked: true`) instead of being overwritten by an in-play NO BET.

## Automation cadence

`pipeline` (ingest → forecast + freeze → price snapshot → best bets → grade → site) and `lineups` (near-kick-off re-forecast → re-price → lock → site) share one concurrency group. GitHub cron on this repo fires only every few hours, so each run ends with `scripts/rearm.sh`, which dispatches exactly one follow-up: the full `pipeline` if none started in the last 3 h, otherwise `lineups` 20 min after the current run started. The crons stay as a restart if the chain ever breaks; set the repo variable `ORACLE_TICK=off` to stop the chain.

## Results grading (post-match)

`python -m oraclefc.cli grade` (run by the daily pipeline for the last 3 days) fetches final scores from FotMob (allow-listed fields only, no odds), takes the **90-minute** score (extra time / penalties ignored, as Jupiter soccer markets settle on regulation time), and grades:

* the forecast frozen **before kick-off**: modal score, 1X2 RPS and log loss, exact-score / top-5 hit, predicted vs actual goals;
* the locked best bet: WIN/LOSS and P&L for 1 unit bought at the recorded ask + fees (win = 1/cost − 1, loss = −1), plus the model-expected units.

Output: `data/results/<date>.json` per day and a running `data/results/record.json`, shown on the dashboard's **Results & Record** tab. Unfinished, postponed or unmatched games are marked as such and never guessed.

## Match context (lineups, injuries, players, xG, weather, rest, travel)

Each forecast fetches live context. All sources are free and keyless, and every payload is
allow-list parsed with odds, poll and prediction fields stripped:

* **FotMob**: projected or confirmed XIs and absences.
* **FPL**: EPL injury status with timestamps.
* **Open-Meteo**: venue weather.
* **Understat**: player xG/xA and minutes.
* **Our own results data**: rest and travel.

Each family went through the same champion/challenger test
([`docs/CONTEXT_BACKTEST.md`](docs/CONTEXT_BACKTEST.md)), with test window 2023-07-01 →
2026-10-27 and Δ = challenger − base:

| Family | n | ΔRPS [95% CI] | Δlog loss [95% CI] | Live |
|---|---|---|---|---|
| Understat xG component | 40,559 | −0.00007 [−0.00010, −0.00004] | −0.00017 [−0.00028, −0.00007] | **applied** |
| Lineup / player ratings (XI xG+xA value, continuity, backup GK) | 5,337 | −0.00026 [−0.00069, +0.00020] | −0.00056 [−0.00189, +0.00088] | shown, not applied |
| Rest / congestion | 40,457 | −0.00003 [−0.00006, +0.00001] | −0.00004 [−0.00014, +0.00007] | shown, not applied |
| Travel | 37,279 | −0.00002 [−0.00008, +0.00005] | −0.00002 [−0.00021, +0.00018] | shown, not applied |
| Weather | 38,549 | −0.00000 [−0.00001, +0.00001] | +0.00002 [−0.00004, +0.00009] | shown, not applied |

Every match report lists:

* confirmed, projected or inferred lineups;
* key absences, with source and timestamp;
* weather, rest and travel;
* a per-factor table of how many percentage points each factor moved (or, if not validated,
  *would have moved*) home/draw/away.

Unconfirmed XIs are simulated as 200 lineup configurations. A `lineups` workflow
re-forecasts fixtures within 3 h of kickoff every 20 minutes. New lineup stages are frozen
as new records; earlier ones are never overwritten.

## Quick start

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
python -m oraclefc.cli ingest                     # ~80 s: download + clean permitted results data
python -m oraclefc.cli ingest-context             # refresh the Understat player/xG snapshot (data/context)
python -m oraclefc.run_context_backtest           # ~25 min: context-feature champion/challenger
python -m oraclefc.cli backtest                   # ~15 min: tune, walk-forward, champion/challenger
python -m oraclefc.cli run --date 2026-10-31 --print   # forecast + freeze every Jupiter game that day
python -m oraclefc.cli edge --date 2026-10-31     # POST-HOC price comparison (after freezing)
python -m oraclefc.run_calibration                # season-ahead calibration layer (needs the context backtest cache)
python -m oraclefc.cli grade --date 2026-10-31    # POST-MATCH grading vs final scores
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

* Lineups, injuries, rest, travel and weather are ingested and shown, but none has yet
  beaten the champion out of sample, so they do not move the probabilities. The lineup
  family is directionally better but not significant. Player ratings exist only for the
  top-5 leagues (Understat).
* There is no archive of historical injury lists, so injuries act only through the lineup
  family.
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
