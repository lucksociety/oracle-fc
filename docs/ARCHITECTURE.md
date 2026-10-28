# ORACLE FC — Architecture

```
             ┌──────────────────────── PERMITTED DATA ONLY ─────────────────────────┐
football-data.co.uk ─┐                                                              │
openfootball UCL ────┼─► ingest/ ─► governance (allow-list + deny-list + schema) ─► store (Parquet + DuckDB)
                     │                                                              │
Jupiter /events ─────┴─► fixtures/jupiter.py  (identity fields only, prices never requested)
                                   │                                                │
                                   ▼                                                │
                         resolve.py (team mapping, honest UNMATCHED)                │
                                   │                                                │
                                   ▼                                                ▼
        models/ (league-avg · home/away · Poisson · Dixon–Coles · dynamic DC · Elo · ensemble)
                                   │
                                   ▼
            simulate.py (exact 11×11 joint distribution · Monte Carlo check · param uncertainty)
                                   │
                                   ▼
            forecast.py ─► report.py (standard text) ─► frozen.py (write-once, SHA-256, ledger)
             └──────────────────────────────────────────────────────────────────────┘
                                   │  (forecasts are FROZEN before anything below runs)
                                   ▼
   market/ (physically separate) ─► jupiter_prices.py snapshot ─► edge.py (model − market)  POST-HOC
```

## Directive Zero enforcement

| Layer | Mechanism | Test |
|---|---|---|
| Ingest | Allow-list of results/stat columns; deny-list regex + bookmaker-prefix detector as backstop; schema validation of the clean table | `tests/test_governance.py` |
| Model input | `GoalModel._train` and `predict_matrix` call `assert_no_market_columns` on every frame | `test_model_input_with_odds_raises` |
| Fixtures | `sanitise_event` copies only identity fields; the module never asks for markets | `tests/test_fixtures.py`, `test_fixture_module_never_reads_prices` |
| Code firewall | No forecasting module may import `oraclefc.market` (AST scan) | `tests/test_firewall.py` |
| Outputs | `assert_no_price_keys` on every forecast before freezing | `test_forecast_output_price_guard` |
| Time ordering | Forecasts are frozen (O_EXCL, read-only, hashed) before any market snapshot; `edge.py` rejects forecasts frozen after the snapshot; no forecast is generated after kickoff | `tests/test_frozen.py` |
| Provenance | `data/clean/provenance.json` records every file URL, retrieval time, SHA-256, kept & dropped fields | — |

## Models

* **League average** and **home/away rate** — baselines (per division, trailing 365 days).
* **Standard Poisson** — attack/defence/home, no decay (classic Maher).
* **Standard Dixon–Coles** — adds the low-score dependence parameter ρ.
* **Dynamic Dixon–Coles (frozen baseline)** — one *global* joint fit over every division plus the
  Champions League, with exponential time decay (half-life tuned), country-specific home advantage,
  and hierarchical ridge shrinkage of each team toward its division's mean attack/defence (MAP).
  Divisions are linked by promotion/relegation and European ties, so strengths are on one scale.
  Analytic gradient + L-BFGS: ~0.75 s per fit on ~40k weighted matches. Diagonal Laplace standard
  errors feed parameter-uncertainty intervals.
* **Goal-based Elo** — independent results-only rating (World-Football-Elo margin multiplier),
  mapped to goal rates with a per-division Poisson regression.
* **Ensemble (challenger)** — linear pool of full score matrices; weights are learned on
  walk-forward *out-of-sample* predictions only (nested: each test season's weights use earlier
  seasons only), optimising the exact-score log score with shrinkage toward equal weights.

Champion/challenger: the ensemble only replaces the frozen baseline if the 95% block-bootstrap
confidence intervals of both ΔRPS and Δexact-score log score are below zero. Every run is appended
to `experiments/experiments.jsonl` (git SHA, params, metrics) and the decision is written to
`experiments/registry.json` (history kept).

## Simulation

The primary engine is the **exact** joint score distribution (0–10 goals each side, renormalised,
Dixon–Coles τ correction). Monte Carlo (adaptive, ≥200k draws, standard errors, convergence flag)
is run as a cross-check and reports max |MC − exact|. Parameter uncertainty is propagated by
sampling the log-rates from their Laplace posterior. The **primary score is the modal exact score**
of the joint distribution — never rounded xG (tested).

## Runtime topology

* **GitHub Actions `pipeline.yml`** (every 3 h + manual with a date): ingest → discover Jupiter
  fixtures for today…+7 days (ET) → forecast & freeze → post-hoc price snapshot → build static site
  → commit frozen forecasts → deploy GitHub Pages.
* **Static dashboard** (GitHub Pages): date picker loads frozen forecasts; dates the pipeline has not
  reached show the live Jupiter fixture list (fetched in the browser) as *awaiting simulation*.
  The Edge tab can fetch live Jupiter prices in the browser and compare them to the frozen forecasts.
* **Local/self-hosted FastAPI** (`python -m oraclefc.cli serve`): the same UI, but picking a date
  runs the full pipeline on demand.
* **`backtest.yml`** (weekly): re-tunes, re-runs the walk-forward backtest, updates `docs/BACKTEST.md`
  and the champion registry.
