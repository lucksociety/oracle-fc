# ORACLE FC — Roadmap

Each item enters as a **challenger** and is promoted only if it beats the champion out of sample
under the predefined rule (95% block-bootstrap CI of ΔRPS and Δexact log score both < 0).

## Near term
1. **Current-season European results** (UCL/UEL/UECL 2026/27) via football-data.org free tier or
   openfootball once published; separate UEL/UECL environments instead of borrowing UCL's.
2. **Domestic cups** (FA Cup, EFL Cup, Copa del Rey, DFB-Pokal) results + a cup-rotation term.
3. **More leagues** on Jupiter that lack a free results feed today: Saudi Pro League, Qatar, Colombia,
   Turkey 1. Lig, Brazil Série B, Spanish Primera/Segunda RFEF (needed for Copa del Rey ties).
4. **xG-informed strengths**: football-data now publishes xG for some divisions (2026/27). Add an
   xG-blended attack/defence challenger once ≥1 season is available out of sample.
5. **Shots / shots-on-target** process model (available back to 2016 for European divisions).

## Medium term
6. **Lineups & injuries**: only from a terms-compliant, point-in-time feed (e.g. paid API-Football
   tier) — snapshots must be stored with retrieval timestamps before kickoff.
7. **Player-level ratings** (minutes-weighted plus-minus / xG chain) aggregated to expected XI strength.
8. **Rest days, travel distance, congestion, weather** (Open-Meteo), each validated separately.
9. **Bivariate Poisson / Weibull-count / negative binomial** score distributions as challengers;
   in-match state-space model for time-varying strengths.

## Longer term
10. **Gradient-boosted (LightGBM) and neural challengers** on engineered pre-match features, predicting
    goal rates, evaluated with the same walk-forward harness.
11. **Automatic results grading** of frozen forecasts and a public track record page.
12. **Calibration layer** (isotonic / beta) fitted only on out-of-sample model outputs — never on markets.
