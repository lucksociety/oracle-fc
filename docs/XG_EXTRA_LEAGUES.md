# xG outside the top five (2026-11-19)

Understat covers five leagues, so everywhere else the xG component was a goals-only model. FotMob match
pages carry team xG for many more leagues (probe: `research/xg_coverage.py`). 21,550 matches were
backfilled for 14 leagues (`research/xg_backfill.py`, stored in `data/context/fotmob_extra_matches.parquet`,
98.7% linked to our results) and tested walk-forward (`research/xg_extra_backtest.py`): weekly refits on data
strictly before each refit, April 2024 → 18 November 2026. Base = production ensemble weights with the xG slot
fitted on goals only (what ran in these leagues). Challenger = the same with xG blended in at the production
weight 0.5. Differences are challenger − base (negative = better) with block-bootstrap 95% intervals.

| League | n | Δ log loss | Δ RPS | Δ exact-score log score |
|---|---|---|---|---|
| **All 14 pooled** | 13,387 | −0.00194 [−0.00247, −0.00140] | −0.00068 [−0.00085, −0.00050] | −0.00473 [−0.00577, −0.00377] |
| Brazil Série A (BRA) | 1,101 | −0.00202 [−0.00365, −0.00036] | −0.00078 [−0.00132, −0.00023] | −0.00620 [−0.00928, −0.00308] |
| Argentina (ARG) | 1,420 | −0.00144 [−0.00300, +0.00016] | −0.00049 [−0.00093, −0.00004] | −0.00385 [−0.00660, −0.00125] |
| MLS (USA) | 1,489 | −0.00294 [−0.00466, −0.00139] | −0.00087 [−0.00145, −0.00036] | −0.00522 [−0.00853, −0.00220] |
| Mexico (MEX) | 876 | −0.00154 [−0.00369, +0.00048] | −0.00059 [−0.00127, +0.00005] | −0.00249 [−0.00577, +0.00087] |
| Japan J1 (JPN) | 851 | −0.00158 [−0.00400, +0.00103] | −0.00043 [−0.00123, +0.00042] | −0.00608 [−0.01018, −0.00159] |
| Portugal (P1) | 775 | +0.00018 [−0.00231, +0.00259] | −0.00001 [−0.00074, +0.00074] | −0.00304 [−0.00683, +0.00052] |
| Netherlands (N1) | 783 | −0.00349 [−0.00635, −0.00055] | −0.00124 [−0.00212, −0.00033] | −0.00769 [−0.01190, −0.00334] |
| Turkey (T1) | 827 | −0.00053 [−0.00356, +0.00234] | −0.00026 [−0.00124, +0.00069] | −0.00239 [−0.00640, +0.00170] |
| Belgium (B1) | 790 | −0.00342 [−0.00565, −0.00109] | −0.00126 [−0.00196, −0.00053] | −0.00600 [−0.01028, −0.00159] |
| Scotland (SC0) | 574 | −0.00177 [−0.00384, +0.00032] | −0.00059 [−0.00127, +0.00015] | −0.00443 [−0.00838, −0.00024] |
| 2. Bundesliga (D2) | 774 | −0.00264 [−0.00496, −0.00019] | −0.00118 [−0.00198, −0.00034] | −0.00641 [−0.01055, −0.00213] |
| Championship (E1) | 1,371 | −0.00336 [−0.00500, −0.00188] | −0.00110 [−0.00165, −0.00058] | −0.00663 [−0.00951, −0.00385] |
| Greece (G1) | 582 | −0.00078 [−0.00222, +0.00061] | −0.00033 [−0.00075, +0.00007] | −0.00095 [−0.00342, +0.00124] |
| LaLiga2 (SP2) | 1,174 | −0.00065 [−0.00189, +0.00045] | −0.00018 [−0.00058, +0.00017] | −0.00314 [−0.00540, −0.00125] |

**Decision: kept** for all 14 leagues, by the pooled result (the keep rule: log loss and RPS both improve and
at least one interval is entirely below zero; here both are). Leagues were not picked individually: per-league
samples are too small to separate Portugal's flat result from noise, and every league shares one mechanism.
Greece and LaLiga2 have xG only from 2025/26, so most of their test window had none.

Other weights on the same test, pooled Δ log loss: 0.3 → −0.00129, 0.5 → −0.00194, 0.7 → −0.00241. The weight
stays at the production 0.5 until a test that also covers the top five leagues says otherwise.

What this is not: the gain is about 0.002 log loss. It does not close the gap to the market, which the live
record puts far higher in these leagues on small samples. Ensemble weights and the calibration layer were
fitted before this data existed; the weekly backtest refits them with it.

The routine pipeline (`ingest-context`) adds newly finished matches for these leagues on every run.
