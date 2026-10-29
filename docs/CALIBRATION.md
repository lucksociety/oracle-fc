# Calibration layer backtest (results only)

Experiment `b41b2eae937d` · test window 2023-07-01 → 2026-10-28 · n = 40,603 matches · layer for season S fitted only on OOS matches from 2022-07-01 to the start of S. Δ = calibrated − base ensemble (negative = better); 95% CIs by block bootstrap over refit weeks.

Adoption rule (fixed in advance): all three Δ < 0 and the CIs of ΔRPS and Δexact-score log score entirely < 0.

Base ensemble: RPS 0.20982 · 1X2 log loss 1.01994 · exact-score log score 2.91447

| Variant | RPS | ΔRPS [95% CI] | Δ1X2 log loss [95% CI] | Δexact log score [95% CI] | Eligible |
|---|---|---|---|---|---|
| global | 0.20982 | -0.00000 [-0.00005, +0.00005] | -0.00029 [-0.00049, -0.00008] | -0.00052 [-0.00094, -0.00009] | no |
| global+sharpen | 0.20975 | -0.00008 [-0.00014, -0.00002] | -0.00058 [-0.00082, -0.00033] | -0.00106 [-0.00156, -0.00052] | **yes** |
| div_goals+sharpen | 0.20993 | +0.00011 [+0.00002, +0.00020] | -0.00002 [-0.00038, +0.00034] | +0.00122 [+0.00033, +0.00207] | no |
| div_goals_draw+sharpen | 0.20994 | +0.00011 [+0.00002, +0.00021] | +0.00014 [-0.00032, +0.00061] | +0.00128 [+0.00037, +0.00214] | no |

**Adopted:** `global+sharpen`

## Reliability of goal-market probabilities (model vs results, test window)

| Market | Bin | n | base pred | base obs | calibrated pred | calibrated obs |
|---|---|---|---|---|---|---|
| under_2.5 | 0.0-0.3 | 394 | 0.261 | 0.254 | 0.256 | 0.269 |
| under_2.5 | 0.3-0.5 | 19797 | 0.438 | 0.416 | 0.432 | 0.424 |
| under_2.5 | 0.5-0.6 | 16585 | 0.544 | 0.527 | 0.543 | 0.531 |
| under_2.5 | 0.6-0.7 | 3569 | 0.633 | 0.606 | 0.634 | 0.613 |
| under_2.5 | 0.7-1.0 | 258 | 0.720 | 0.709 | 0.721 | 0.716 |
| under_3.5 | 0.3-0.5 | 312 | 0.451 | 0.471 | 0.451 | 0.490 |
| under_3.5 | 0.5-0.6 | 2428 | 0.568 | 0.537 | 0.566 | 0.556 |
| under_3.5 | 0.6-0.7 | 13508 | 0.659 | 0.649 | 0.658 | 0.658 |
| under_3.5 | 0.7-1.0 | 24350 | 0.760 | 0.752 | 0.760 | 0.755 |
| btts_no | 0.3-0.5 | 25806 | 0.447 | 0.431 | 0.437 | 0.439 |
| btts_no | 0.5-0.6 | 13818 | 0.533 | 0.501 | 0.532 | 0.509 |
| btts_no | 0.6-0.7 | 976 | 0.624 | 0.591 | 0.624 | 0.594 |
| home_under_1.5 | 0.0-0.3 | 992 | 0.243 | 0.214 | 0.239 | 0.223 |
| home_under_1.5 | 0.3-0.5 | 9620 | 0.431 | 0.412 | 0.428 | 0.429 |
| home_under_1.5 | 0.5-0.6 | 12784 | 0.553 | 0.548 | 0.552 | 0.559 |
| home_under_1.5 | 0.6-0.7 | 12519 | 0.645 | 0.639 | 0.645 | 0.646 |
| home_under_1.5 | 0.7-1.0 | 4688 | 0.743 | 0.732 | 0.744 | 0.737 |
| away_under_1.5 | 0.0-0.3 | 126 | 0.253 | 0.246 | 0.251 | 0.238 |
| away_under_1.5 | 0.3-0.5 | 2755 | 0.437 | 0.412 | 0.435 | 0.422 |
| away_under_1.5 | 0.5-0.6 | 6529 | 0.558 | 0.549 | 0.558 | 0.553 |
| away_under_1.5 | 0.6-0.7 | 14326 | 0.654 | 0.645 | 0.654 | 0.647 |
| away_under_1.5 | 0.7-1.0 | 16867 | 0.759 | 0.750 | 0.761 | 0.750 |
| draw | 0.0-0.3 | 39211 | 0.249 | 0.259 | 0.255 | 0.258 |
| draw | 0.3-0.5 | 1392 | 0.312 | 0.328 | 0.313 | 0.314 |
