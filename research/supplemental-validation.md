# Supplemental league validation — November 11, 2026

Results-only, weekly chronological Dixon–Coles evaluation. Model parameters are the
registered champion's parameters. Training excludes the preceding calendar day
because historical rows lack exact final-score publication timestamps. Team
coverage must have at least eight weighted matches. Temperatures are chosen on
2025 only; evaluation uses 2026 through November 10. No betting prices enter this
research or the forecast.

Eligibility requires at least 200 forecasts in each period, improvement over a
past-results league H/D/A prior on both log loss and Brier score with 99% weekly
cluster bootstrap intervals below zero, and no deterioration versus the raw model
in heldout 1X2 or exact-score log loss. This is a league-level screening criterion,
not a simultaneous confidence guarantee or evidence of profitable execution.

Only Peru (267 heldout forecasts) and Venezuela (211) passed. Both retain the raw
model temperature of 1.0: there is no probability retuning for these leagues.
Colombia, Colombia 2, Brazil 2, Germany 3, Mexico 2, Paraguay, Argentina 2 and Costa
Rica remain forecast-only. Costa Rica has insufficient samples for evaluation.
Other failures include uncertain baseline improvement and deterioration relative
to the raw model. Per-league metrics are in experiments/supplemental-policy.json.

The policy is bound to the exact model parameters and is unavailable before all
its outcomes could have been observed. Normal fixture, coverage, freshness,
score-agreement, >50% probability, fee, EV and execution checks still apply.
Predictions remain visible when betting is blocked. Friendlies remain forecast-only.

Reproduce from the repository root after refreshing the allowlisted historical
results (the source parquet must include the supplemental leagues):

```sh
python research/validate_supplemental.py \
  --data data/clean/matches.parquet --through 2026-11-10 \
  --oos-cache /tmp/supplemental-oos.npz \
  --output /tmp/supplemental-policy.json
```

Review future research prospectively. Do not promote parameters or unlock leagues
from daily betting outcomes. Existing results reconciliation and prospective
forecast/bet ledgers continue collecting future evidence.


Policy timing correction (November 12): a live scan uses the current decision
time for validation eligibility, independently of the last ingested results date.
Nested supplemental engines inherit that decision time. Explicit historical
cutoffs retain point-in-time restrictions. Training inputs and their cutoff are
unchanged; stale results cannot make a published validation policy disappear.
