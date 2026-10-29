# Model and Discord review — 2026-10-29

A partly invalid component matrix previously lost probability mass instead of being excluded consistently. The ensemble now excludes the whole invalid component per fixture and renormalizes the remaining weights; negative/non-finite weights fail explicitly. Valid forecasts are unchanged.

`/soccer` previously read published snapshots. The default Worker route now dispatches `discord-soccer.yml`, which ingests permitted results, runs and freezes the model, compares prices afterward, then builds Discord embeds from the run's local date file. The interaction token is AES-GCM encrypted in public workflow inputs. `RUN_MODE=snapshot` explicitly restores cached-only behavior.

Validation: 54 Python tests and 5 Node test files pass, including signed request -> correct workflow -> authenticated relay round-trip, invalid dates, and missing configuration. Local response builder passes against committed frozen fixtures. No measured historical accuracy gain is claimed for the ensemble guard. Full retraining/backtesting needs the ignored raw/clean datasets.

A read-only PR workflow now runs the model/command regressions. No dashboard presentation files were changed.

## Deployment prerequisites

Merge the workflow to main before deploying the Worker. Configure Worker secrets GITHUB_TOKEN (Actions:write for this repository) and RELAY_KEY; put the same RELAY_KEY in GitHub Actions secrets. Keep the existing Discord application ID/public key and interaction URL. Deploy from `discord/` using the existing Wrangler flow. Never put tokens in command inputs or source. The dedicated workflow saves response and forecast provenance artifacts for 14 days; it does not publish dashboard files or commit its new freezes. Its run artifacts must be retained separately for long-term grading. Queue delay plus runtime must fit Discord's 15-minute interaction lifetime; deployment must confirm this with a real command.
