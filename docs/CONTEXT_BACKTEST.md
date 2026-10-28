# Context-feature backtest (lineups, players, rest, travel, weather, xG)

Experiment `66e58abd37c6` · data cutoff 2026-10-27 · test window 2023-07-01 → 2026-10-27 · feature coefficients trained from 2022-07-01 with nested (season-ahead) refits.

Differences are **challenger − base** on the matches where the feature exists (negative = better). 95% CIs: block bootstrap over refit weeks.

Keep rule (pre-registered): ΔRPS < 0 **and** Δlog-loss < 0, with at least one 95% CI entirely < 0.

| Feature family | Matches | ΔRPS [95% CI] | Δ1X2 log loss [95% CI] | Δexact-score log score | Kept |
|---|---|---|---|---|---|
| xg_component_top5 | 5,650 | -0.00042 [-0.00065, -0.00021] | -0.00104 [-0.00177, -0.00037] | -0.00268 | **yes** |
| xg_component_all | 40,559 | -0.00007 [-0.00010, -0.00004] | -0.00017 [-0.00028, -0.00007] | -0.00042 | **yes** |
| rest | 40,457 | -0.00003 [-0.00006, +0.00001] | -0.00004 [-0.00014, +0.00007] | -0.00003 | no |
| travel | 37,279 | -0.00002 [-0.00008, +0.00005] | -0.00002 [-0.00021, +0.00018] | -0.00023 | no |
| weather | 38,549 | -0.00000 [-0.00001, +0.00001] | +0.00002 [-0.00004, +0.00009] | -0.00036 | no |
| lineup | 5,337 | -0.00026 [-0.00069, +0.00020] | -0.00056 [-0.00189, +0.00088] | -0.00120 | no |

## What this means (written after the results; the numbers above are unedited)

* **Understat xG: kept.** Adding a Dixon–Coles model fitted to 0.5·goals + 0.5·xG as an
  ensemble component improved RPS and log loss, with both 95% CIs below zero, both in the
  top-5 leagues (n = 5,650; RPS 0.19939 → 0.19897, log loss 0.98501 → 0.98397) and overall
  (n = 40,559; RPS 0.20991 → 0.20984). The production ensemble is now `1.1.0+ensemble-xg`,
  with weights xg_dc 0.513, elo 0.438, dynamic_dc 0.044, standard_dc 0.003 and
  home_away_rate 0.002. Outside the top-5 leagues no xG exists, so xg_dc reduces to a goals
  model there.
* **Lineups / player ratings: not kept (inconclusive, not negative).** The adjustment used
  the confirmed starting XI's xG+xA value relative to the team's recent XIs, its
  continuity, and a backup-keeper flag.
  * Both point estimates improved: RPS −0.00026 and log loss −0.00056 on 5,337 matches.
  * Both 95% CIs include zero, so it fails the pre-registered rule.
  * Top-5 exact-score accuracy fell from 49.7% to 49.2%.
  * The fitted direction is sensible: a stronger XI scores more (β = +0.27 per log unit),
    and goals rise when the opponent starts a backup keeper (+0.035). The uncertainty is
    large, though, with only about 2.5 seasons of usable top-5 history.
* **Rest/congestion and travel: not kept.** Tiny favourable point estimates, with CIs
  spanning zero.
* **Weather: not kept.** No 1X2 improvement; log loss was slightly worse. The exact-score
  log score improved (−0.00036, CI below zero), mostly through rain, but the keep rule is
  about 1X2 RPS and log loss.
* **Injuries/suspensions** have no historical archive, so no separate coefficient can be
  validated. They act only through the lineup family, which is not applied.

Live reports therefore show lineups (confirmed, projected or inferred), absences with
source and timestamp, weather, rest and travel. The probabilities move only through the
validated xG component.

Each failed family's per-factor shift is reported as "not applied". The owner can switch on
an unvalidated family through `registry.champion.context.apply_unvalidated` (e.g.
`["lineup"]`). It is then applied at 50% of the fitted size and flagged UNVALIDATED in every
report.

## Production coefficients (log expected-goals multipliers per unit of feature)

| Family | Parameter | β | s.e. | Kept |
|---|---|---|---|---|
| rest | short_rest_own | +0.0510 | 0.0542 | no (not applied) |
| rest | short_rest_opp | -0.0183 | 0.3158 | no (not applied) |
| rest | congestion_own | -0.0909 | 0.7802 | no (not applied) |
| rest | congestion_opp | +0.1002 | 0.7455 | no (not applied) |
| travel | travel_home_boost | +0.0154 | 0.1401 | no (not applied) |
| travel | travel_away_penalty | +0.0065 | 0.1238 | no (not applied) |
| weather | rain | +0.2199 | 0.2807 | no (not applied) |
| weather | wind | -0.0481 | 0.0797 | no (not applied) |
| weather | heat | +0.0493 | 0.1547 | no (not applied) |
| weather | cold | -0.0477 | 0.9075 | no (not applied) |
| lineup | xi_attack_own | +0.2743 | 0.5087 | no (not applied) |
| lineup | xi_continuity_own | +0.0252 | 0.0874 | no (not applied) |
| lineup | xi_continuity_opp | -0.0170 | 0.0769 | no (not applied) |
| lineup | backup_gk_opp | +0.0346 | 0.1712 | no (not applied) |

## Feature definitions

* **rest**: short_rest = clip((5 − days since previous match)/3, 0, 1); congestion = clip((matches in previous 21 days − 4)/3, 0, 1). History contains league + UCL matches only (domestic cups/UEL/UECL missing → rest over-stated in cup weeks).
* **travel**: log(1 + km/100) between the two clubs' home stadiums (FotMob venue coordinates); acts on the home and away scoring rates separately.
* **weather**: NASA POWER (MERRA-2) hourly reanalysis at the stadium for the two kickoff hours (history); Open-Meteo forecast for live matches. rain = min(mm,10)/10, wind = clip((m/s − 8)/6, 0, 1.5), heat = clip((°C − 24)/8, 0, 1.5), cold = clip((2 − °C)/8, 0, 1.5); acts on both teams' scoring.
* **lineup** (Understat top-5 leagues): XI attack = log(Σ starters' shrunk xG+xA per 90 / mean of the team's previous 6 XIs); continuity = Σ starters' recent minutes share − previous-6 mean; backup GK = starting keeper is not the regular (regular ≥ 50% recent minutes). Confirmed starting XIs of the match itself are used (published ~60 min before kickoff).
* **xG component**: dynamic Dixon–Coles fitted to 0.5·goals + 0.5·Understat xG, added to the ensemble.

Unvalidated (no point-in-time history) — applied conservatively and flagged in every report:

* Projected (unconfirmed) lineups are simulated as 200 XI configurations: each projected starter starts with p=0.85 (doubtful players: FPL chance of playing, else 0.5), otherwise the slot is filled by an available same-position squad player drawn in proportion to recent minutes share. Before any XI is published, the XI is inferred from recent minutes share minus listed absences (p=0.70 per starter). Outside the Understat top-5 leagues no point-in-time player ratings exist, so lineups are shown but NOT applied.
* Injury/suspension lists (FotMob, FPL) are only used to build projected XIs; their effect flows through the validated lineup coefficients — there is no separate injury coefficient.
