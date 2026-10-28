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

## 4. Match-context sources (added 2026-10-28; each verified live with curl that day)

All are free and keyless. Every payload is parsed through an **allow-list**, and
`governance.assert_no_market_keys` runs on each parsed object. Odds, polls, "predictions",
tipster fields, fantasy prices and transfer values are never copied. Whether each family
*moves the probabilities* is decided by the out-of-sample test in
[CONTEXT_BACKTEST.md](CONTEXT_BACKTEST.md). Families that fail it are shown in reports for
information only.

| Source | Endpoint | Used for | Point-in-time history? | Stripped |
|---|---|---|---|---|
| **Understat** | `understat.com/getLeagueData/{league}/{season}`, `/getMatchData/{id}` (header `X-Requested-With: XMLHttpRequest`) | Match xG (top-5 leagues, 2019→), per-player minutes, position, xG, xA per match; used for player ratings, minutes shares, XI strength, continuity and the backup-GK flag | **Yes**: per-match rows with dates, replayed chronologically | the `forecast` (win-probability) block in `dates[]` |
| **FotMob** | `fotmob.com/api/data/matchDetails?matchId=`, `matches?date=`, `teams?id=`, `leagues?id=&season=` | Projected (`lineupType=predicted`, source enetpulse) vs confirmed XIs, formation, unavailable players (injury/suspension, expected return), stadium coordinates, exact UTC kickoffs | Partial: confirmed XIs of past matches yes; *projected* XIs and injury lists are not archived, so they are not back-testable | `matchFacts.poll` (incl. `oddspoll`), betting/insight blocks, player market values |
| **Fantasy Premier League** | `fantasy.premierleague.com/api/bootstrap-static/` | EPL status (injured/suspended/doubtful), `chance_of_playing_next_round`, news text and `news_added` timestamp | No | prices, ownership, transfers, expected points |
| **Open-Meteo** | `api.open-meteo.com/v1/forecast` (`wind_speed_unit=ms`, UTC) | Live venue weather for the two kickoff hours: temperature, wind, precipitation | n/a (forecast) | — |
| **NASA POWER** | `power.larc.nasa.gov/api/temporal/hourly/point` (MERRA-2) | Historical kickoff weather at each stadium (backtest). Open-Meteo's archive fair-use weighting made multi-year history for ~500 venues impractical | **Yes** (reanalysis) | — |
| Our results data | football-data + openfootball | Rest days and matches in the previous 21 days (league + UCL) | Yes | odds columns (see §1) |

Live vs. history mismatch, documented: the backtest uses reanalysis weather (what actually
happened). Live forecasts use a weather forecast, so the live weather effect carries
forecast error that the backtest does not.

### Assessed and not used

| Source | Status on 2026-10-28 |
|---|---|
| Sofascore API | HTTP 403 (anti-bot) |
| Transfermarkt | HTTP 405; no API |
| FBref | HTTP 403 (Cloudflare) |
| ESPN site API | Works (rosters, venue) but has no injury feed and embeds odds/pickcenter blocks. FotMob covers the same data more completely, so ESPN is not ingested |
| **API-Football** (api-sports.io) | Needs a key (`x-apisports-key`; free tier 100 req/day). It would add injuries and lineups for leagues FotMob covers thinly. **Not integrated**: no key is configured, and the free sources already cover lineups and injuries. If added, the repo secret would be `API_FOOTBALL_KEY` |
| Any odds/market/tipster/power-ranking data | **Prohibited by Directive Zero** |

## Lineups & injuries

* Top-5 leagues: Understat player histories give each XI a point-in-time attacking value
  (shrunk xG+xA per 90), a continuity score (recent minutes share of the starters) and a
  backup-goalkeeper flag.
* Live forecasts read FotMob's projected or confirmed XI and absences (plus FPL for the
  EPL), then simulate 200 XI configurations when the XI is not confirmed.
* Before any XI is published, the XI is inferred from minutes share minus listed absences.
* Injuries affect the forecast **only through the lineup** (who is expected to start). No
  separate injury coefficient exists, because no archive of historical injury lists was
  available to validate one.
* Outside the top-5 leagues, lineups and absences are shown but not applied, because no
  player-rating history exists there.

## Competitions on Jupiter that ORACLE FC cannot yet forecast

Saudi Pro League (`spl`), Qatar (`qat1`), Colombia (`col1`), Turkey 1. Lig (`tur2`),
Brazil Série B (`bra2`) and lower-league clubs in domestic cups (e.g. Copa del Rey
Segunda RFEF sides). These appear in the dashboard under *Not forecast* with the exact reason.
