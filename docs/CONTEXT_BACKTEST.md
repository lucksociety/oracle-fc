# Context-feature backtest (lineups, players, rest, travel, weather, xG)

Experiment `e64a0baadb30` · data cutoff 2026-11-22 · test window 2023-07-01 → 2026-11-22 · feature coefficients trained from 2022-07-01 with nested (season-ahead) refits.

Differences are **challenger − base** on the matches where the feature exists (negative = better). 95% CIs: block bootstrap over refit weeks.

Keep rule (pre-registered): ΔRPS < 0 **and** Δlog-loss < 0, with at least one 95% CI entirely < 0.

| Feature family | Matches | ΔRPS [95% CI] | Δ1X2 log loss [95% CI] | Δexact-score log score | Kept |
|---|---|---|---|---|---|
| xg_component_top5 | 5,801 | -0.00056 [-0.00084, -0.00028] | -0.00144 [-0.00235, -0.00055] | -0.00386 | **yes** |
| xg_component_all | 41,487 | -0.00037 [-0.00044, -0.00030] | -0.00103 [-0.00125, -0.00082] | -0.00236 | **yes** |
| rest | 41,386 | -0.00003 [-0.00006, +0.00001] | -0.00005 [-0.00015, +0.00005] | -0.00002 | no |
| travel | 38,151 | -0.00002 [-0.00009, +0.00004] | -0.00006 [-0.00025, +0.00014] | -0.00014 | no |
| weather | 39,238 | -0.00001 [-0.00002, +0.00000] | +0.00001 [-0.00006, +0.00008] | -0.00035 | no |
| lineup | 5,480 | -0.00026 [-0.00069, +0.00019] | -0.00054 [-0.00182, +0.00081] | -0.00116 | no |

## Production coefficients (log expected-goals multipliers per unit of feature)

| Family | Parameter | β | s.e. | Kept |
|---|---|---|---|---|
| rest | short_rest_own | +0.0509 | 0.1986 | no (not applied) |
| rest | short_rest_opp | -0.0211 | 0.2298 | no (not applied) |
| rest | congestion_own | -0.0877 | 0.6463 | no (not applied) |
| rest | congestion_opp | +0.0973 | 0.7597 | no (not applied) |
| travel | travel_home_boost | +0.0141 | 0.2149 | no (not applied) |
| travel | travel_away_penalty | +0.0046 | 0.1930 | no (not applied) |
| weather | rain | +0.2215 | 0.6783 | no (not applied) |
| weather | wind | -0.0532 | 0.2269 | no (not applied) |
| weather | heat | +0.0430 | 0.1106 | no (not applied) |
| weather | cold | -0.0489 | 0.6158 | no (not applied) |
| lineup | xi_attack_own | +0.2735 | 0.3214 | no (not applied) |
| lineup | xi_continuity_own | +0.0245 | 0.0785 | no (not applied) |
| lineup | xi_continuity_opp | -0.0163 | 0.1025 | no (not applied) |
| lineup | backup_gk_opp | +0.0356 | 0.1116 | no (not applied) |

## Feature definitions

* **rest**: short_rest = clip((5 − days since previous match)/3, 0, 1); congestion = clip((matches in previous 21 days − 4)/3, 0, 1). History contains league + UCL matches only (domestic cups/UEL/UECL missing → rest over-stated in cup weeks).
* **travel**: log(1 + km/100) between the two clubs' home stadiums (FotMob venue coordinates); acts on the home and away scoring rates separately.
* **weather**: NASA POWER (MERRA-2) hourly reanalysis at the stadium for the two kickoff hours (history); Open-Meteo forecast for live matches. rain = min(mm,10)/10, wind = clip((m/s − 8)/6, 0, 1.5), heat = clip((°C − 24)/8, 0, 1.5), cold = clip((2 − °C)/8, 0, 1.5); acts on both teams' scoring.
* **lineup** (Understat top-5 leagues): XI attack = log(Σ starters' shrunk xG+xA per 90 / mean of the team's previous 6 XIs); continuity = Σ starters' recent minutes share − previous-6 mean; backup GK = starting keeper is not the regular (regular ≥ 50% recent minutes). Confirmed starting XIs of the match itself are used (published ~60 min before kickoff).
* **xG component**: dynamic Dixon–Coles fitted to 0.5·goals + 0.5·Understat xG, added to the ensemble.

Unvalidated (no point-in-time history) — applied conservatively and flagged in every report:

* Projected (unconfirmed) lineups are simulated as 200 XI configurations: each projected starter starts with p=0.85 (doubtful players: FPL chance of playing, else 0.5), otherwise the slot is filled by an available same-position squad player drawn in proportion to recent minutes share. Before any XI is published, the XI is inferred from recent minutes share minus listed absences (p=0.70 per starter). Outside the Understat top-5 leagues no point-in-time player ratings exist, so lineups are shown but NOT applied.
* Injury/suspension lists (FotMob, FPL) are only used to build projected XIs; their effect flows through the validated lineup coefficients — there is no separate injury coefficient.
