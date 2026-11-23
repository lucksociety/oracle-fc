# Calibration layer backtest (results only)

Experiment `d4817e231f28` · test window 2023-07-01 → 2026-11-22 · n = 41,487 matches · layer for season S fitted only on OOS matches from 2022-07-01 to the start of S. Δ = calibrated − base ensemble (negative = better); 95% CIs by block bootstrap over refit weeks.

Adoption rule (fixed in advance): all three Δ < 0 and the CIs of ΔRPS and Δexact-score log score entirely < 0.

Base ensemble: RPS 0.20944 · 1X2 log loss 1.01806 · exact-score log score 2.91513

| Variant | RPS | ΔRPS [95% CI] | Δ1X2 log loss [95% CI] | Δexact log score [95% CI] | Eligible |
|---|---|---|---|---|---|
| global | 0.20945 | +0.00001 [-0.00004, +0.00006] | -0.00024 [-0.00044, -0.00004] | -0.00031 [-0.00068, +0.00006] | no |
| global+sharpen | 0.20932 | -0.00013 [-0.00018, -0.00007] | -0.00074 [-0.00100, -0.00049] | -0.00105 [-0.00157, -0.00058] | **yes** |
| div_goals+sharpen | 0.20950 | +0.00006 [-0.00003, +0.00016] | -0.00020 [-0.00057, +0.00015] | +0.00108 [+0.00022, +0.00193] | no |
| div_goals_draw+sharpen | 0.20950 | +0.00006 [-0.00004, +0.00016] | -0.00007 [-0.00055, +0.00039] | +0.00111 [+0.00025, +0.00199] | no |

**Adopted:** `global+sharpen`

## Reliability of goal-market probabilities (model vs results, test window)

| Market | Bin | n | base pred | base obs | calibrated pred | calibrated obs |
|---|---|---|---|---|---|---|
| under_2.5 | 0.0-0.3 | 394 | 0.261 | 0.251 | 0.259 | 0.260 |
| under_2.5 | 0.3-0.5 | 20902 | 0.436 | 0.418 | 0.430 | 0.424 |
| under_2.5 | 0.5-0.6 | 16531 | 0.544 | 0.527 | 0.543 | 0.532 |
| under_2.5 | 0.6-0.7 | 3518 | 0.632 | 0.616 | 0.633 | 0.621 |
| under_2.5 | 0.7-1.0 | 142 | 0.715 | 0.732 | 0.716 | 0.747 |
| under_3.5 | 0.3-0.5 | 314 | 0.452 | 0.462 | 0.451 | 0.480 |
| under_3.5 | 0.5-0.6 | 2658 | 0.567 | 0.531 | 0.566 | 0.558 |
| under_3.5 | 0.6-0.7 | 14280 | 0.659 | 0.650 | 0.657 | 0.658 |
| under_3.5 | 0.7-1.0 | 24229 | 0.759 | 0.754 | 0.759 | 0.756 |
| btts_no | 0.3-0.5 | 27252 | 0.445 | 0.432 | 0.435 | 0.439 |
| btts_no | 0.5-0.6 | 13518 | 0.533 | 0.506 | 0.532 | 0.515 |
| btts_no | 0.6-0.7 | 712 | 0.619 | 0.591 | 0.618 | 0.598 |
| home_under_1.5 | 0.0-0.3 | 987 | 0.244 | 0.208 | 0.240 | 0.229 |
| home_under_1.5 | 0.3-0.5 | 9972 | 0.431 | 0.406 | 0.429 | 0.425 |
| home_under_1.5 | 0.5-0.6 | 13440 | 0.553 | 0.550 | 0.552 | 0.559 |
| home_under_1.5 | 0.6-0.7 | 12710 | 0.645 | 0.644 | 0.645 | 0.650 |
| home_under_1.5 | 0.7-1.0 | 4378 | 0.741 | 0.735 | 0.742 | 0.740 |
| away_under_1.5 | 0.0-0.3 | 121 | 0.255 | 0.240 | 0.252 | 0.230 |
| away_under_1.5 | 0.3-0.5 | 2826 | 0.438 | 0.407 | 0.435 | 0.420 |
| away_under_1.5 | 0.5-0.6 | 6801 | 0.559 | 0.543 | 0.558 | 0.551 |
| away_under_1.5 | 0.6-0.7 | 15038 | 0.654 | 0.648 | 0.654 | 0.649 |
| away_under_1.5 | 0.7-1.0 | 16701 | 0.757 | 0.753 | 0.760 | 0.751 |
| draw | 0.0-0.3 | 40200 | 0.250 | 0.258 | 0.254 | 0.256 |
| draw | 0.3-0.5 | 1287 | 0.310 | 0.332 | 0.312 | 0.323 |
