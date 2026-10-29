# ORACLE FC · Discord `/soccer`

A Cloudflare Worker that serves the Discord interactions endpoint for the `/soccer` slash command.

`/soccer [date] [only_bets]` reads the Best Bets snapshot the ORACLE FC pipeline publishes to
GitHub Pages (`data/edge/<date>.json`, plus `data/dates/<date>.json` for counts) and posts:

- a summary embed (bets / no bets / games not forecast, price snapshot time, the rule),
- one gold embed per BET game: pick + side, Jupiter ask, model probability, EV per $1, edge, cost incl. fee, volume / thin-book flag,
- compact "NO BET" embeds listing each remaining game with the reason or the closest miss,
- a button linking to the dashboard for that date.
- the **model version** that produced the picks (newest frozen forecast version among the games),
- 🔒 for games that already kicked off: the pick shown is the one **locked at the last pre-kick-off price** (never an in-play price),
- once graded (`data/results/<date>.json`): final 90′ score and WIN/LOSS ± units per pick, the day's record, and a
  **running record** line from `data/results/record.json` (1 unit per bet at the recorded ask + fees).

`date` accepts `YYYY-MM-DD`, `MM/DD`, `MM-DD-YY`, `today`, `tomorrow`; default is today in America/New_York.
Games already kicked off are flagged, since their prices are stale.

Flow: Ed25519 signature check → PING returns PONG → `/soccer` returns a deferred reply (type 5) →
`ctx.waitUntil` edits the original response and posts follow-ups (≤10 embeds / ≤6000 chars each)
through the interaction webhook. The model never sees prices here; this only relays the post-hoc comparison.

## Config

| Name | Kind | Value |
|---|---|---|
| `DISCORD_APPLICATION_ID` | var | `1565128574128754708` |
| `DISCORD_PUBLIC_KEY` | var | the app's Public Key (Developer Portal → General Information) |
| `SITE_URL` | var | `https://lucksociety.github.io/oracle-fc` |

No secrets are needed at runtime: replies go through the interaction token. The bot token is only
used once, from your own machine, to register the command.

## Deploy

```sh
cd discord
npx wrangler deploy --var DISCORD_PUBLIC_KEY:<public key>
```

## Register the command and endpoint (one-off)

```sh
# global command (appears in every server the app is installed in, can take a few minutes)
curl -X PUT "https://discord.com/api/v10/applications/1565128574128754708/commands" \
  -H "Authorization: Bot $DISCORD_BOT_TOKEN" -H "content-type: application/json" --data @commands.json
# point Discord at the Worker (Discord sends a signed PING to verify it)
curl -X PATCH "https://discord.com/api/v10/applications/@me" \
  -H "Authorization: Bot $DISCORD_BOT_TOKEN" -H "content-type: application/json" \
  --data '{"interactions_endpoint_url":"https://oracle-fc-discord.<subdomain>.workers.dev/"}'
```

Or paste the Worker URL into Developer Portal → General Information → Interactions Endpoint URL.

## Invite

https://discord.com/oauth2/authorize?client_id=1565128574128754708&scope=bot%20applications.commands&permissions=18432

## Test locally

```sh
node test/local.test.mjs                 # signature verify, PING, deferred reply, date parsing
node test/embeds.test.mjs 2026-10-31     # builds the embeds from live dashboard data (no Discord calls)
```
