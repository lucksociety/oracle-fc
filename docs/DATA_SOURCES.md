# ORACLE FC — Data Source Assessment (Phase 1)

Every source below is **free**. Each was assessed for coverage, fields, historical depth,
cost, licensing, update frequency and **point-in-time availability** (can we reconstruct
what was knowable *before* a given kickoff?). Nothing in the model is fabricated: when a
team or competition is not covered, ORACLE FC says so and produces no forecast.

## 1. football-data.co.uk — results & match statistics (PRIMARY)

| Item | Detail |
|---|---|
| URL | `https://football-data.co.uk/mmz4281/{season}/{DIV}.csv` (22 European divisions) and `https://football-data.co.uk/new/{CODE}.csv` (15 extra leagues) |
| Coverage | England E0–E3 + National League (EC), Scotland SC0–SC3, Germany D1–D2, Italy I1–I2, Spain SP1–SP2, France F1–F2, Netherlands N1, Belgium B1, Portugal P1, Turkey T1, Greece G1; extra: Argentina, Austria, Brazil Série A, China, Denmark, Finland, Ireland, Japan, Mexico, Norway, Poland, Romania, Sweden, Switzerland, USA (MLS) |
| Depth used | 2016/17 → present (123,764 matches at last build; cut-off 2026-10-27) |
| Fields KEPT | date, kickoff time, home/away team, full-time & half-time goals, shots, shots on target, corners, yellow/red cards; xG columns where the file provides them (2026/27 only, a handful of divisions) |
| Fields DROPPED | **every bookmaker / exchange / average / max / Asian-handicap / over-under column** (B365*, PS*, BW*, IW*, WH*, VC*, Bb*, Max*, Avg*, AH*, BF*, 1XB*, …). Dropping is done by an allow-list (`governance.FOOTBALL_DATA_ALLOWED`) plus a deny-list regex as a second guard; the dropped column *names* are recorded in `data/clean/provenance.json` for audit |
| Cost / licence | Free for personal and research use; attribution requested. Raw files (which contain odds) are never committed to this repo (`data/raw/` is git-ignored) |
| Update frequency | Typically within 1–3 days of matches (main divisions twice weekly) |
| Point-in-time | Results are immutable facts with match dates, so “everything with `date < kickoff`” is a faithful point-in-time snapshot. The model is always fitted on matches strictly before the forecast/back-test date (`GoalModel._train`) |
| Weaknesses | No lineups, injuries, player data; xG only very recently; extra-league files have no shots; cup competitions (FA Cup, EFL Cup, Copa del Rey, DFB-Pokal) are **not** included |

## 2. openfootball / champions-league — UEFA Champions League results

| Item | Detail |
|---|---|
| URL | `https://raw.githubusercontent.com/openfootball/champions-league/master/{season}/cl.txt` |
| Coverage | UEFA Champions League (league/group stage, knockouts, final), 2016/17 → 2025/26 (1,372 matches) |
| Fields | date, kick-off, teams with UEFA country code, full-time score; for a.e.t./penalties the **90-minute** score is used |
| Cost / licence | Free, public domain (CC0) |
| Update frequency | Community maintained; the current season (2026/27) file was **not yet published** at build time, so European links rely on 2016–2026 results |
| Purpose | Cross-league calibration: the global Dixon–Coles fit links leagues through promotion/relegation *and* through European matches, so a Bundesliga vs Premier League strength gap is learned from data instead of assumed |
| Mapping | Clubs are mapped to domestic names within their country (`teams.match_team`). Unmatched clubs (e.g. from leagues not ingested) keep a namespaced key and are reported in `store.build()` output |

## 3. Jupiter Prediction API — fixture discovery ONLY

| Item | Detail |
|---|---|
| URL | `https://api.jup.ag/prediction/v1/events?category=sports&tags=soccer` (keyless, rate-limited; optional `x-api-key` header via `JUPITER_API_KEY`) |
| Used for | *Which* games exist on a date: event id, team names, competition, kickoff |
| Stripped | All prices, volumes, liquidity and market objects. `fixtures/jupiter.py::sanitise_event` copies an allow-list of identity fields and never requests `includeMarkets` (enforced by `tests/test_firewall.py`) |
| Separate use | `oraclefc/market/` (physically separate, never imported by forecasting code) fetches prices **after** forecasts are frozen for the post-hoc Edge tab |
| Limits | Only active/upcoming events are listed — past dates disappear, so ORACLE FC stores frozen forecasts and serves those for past dates. HTTP 429 on rapid paging (handled with back-off + 10-minute cache) |

## 4. Sources assessed and NOT used (yet)

| Source | Why not (now) |
|---|---|
| Understat / FBref xG | Scraping terms / anti-bot measures; no stable free API. Roadmap item: add as challenger feature once a terms-compliant feed is confirmed |
| API-Football, football-data.org, SportMonks free tiers | Require keys; lineups/injuries are limited or paid on free tiers. football-data.org free tier could provide current-season UCL/UEL fixtures & results (roadmap) |
| Transfermarkt (injuries, values) | No API; scraping not permitted |
| Weather APIs (Open-Meteo) | Free and feasible, but no validated gain yet → roadmap |
| Any odds/market/tipster/power-ranking data | **Prohibited by Directive Zero** |

## Lineups & injuries

No free, terms-compliant, point-in-time lineup or injury feed was found that covers the
leagues ORACLE FC forecasts. Every report therefore states in **DATA QUALITY** that
lineups, injuries and suspensions are not modelled and typical availability is assumed.

## Competitions on Jupiter that ORACLE FC cannot yet forecast

Saudi Pro League (`spl`), Qatar (`qat1`), Colombia (`col1`), Turkey 1. Lig (`tur2`),
Brazil Série B (`bra2`) and lower-league clubs in domestic cups (e.g. Copa del Rey
Segunda RFEF sides). These appear in the dashboard under *Not forecast* with the exact reason.
