#!/usr/bin/env bash
# Keep the scan cadence without relying on GitHub cron (scheduled runs on this repo fire only
# every ~4-7 h). Each pipeline/lineups run ends by dispatching exactly ONE follow-up run:
#   * the full pipeline if none has started in the last PIPELINE_EVERY_MIN minutes, else
#   * the near-kick-off lineups refresh, spaced LINEUPS_EVERY_MIN after this run started.
# Only one follow-up is dispatched because both workflows share one concurrency group and a
# second pending run would cancel the first. The crons stay as a restart if the chain breaks.
# Kill switch: set the repo variable ORACLE_TICK=off.
set -euo pipefail
: "${GH_TOKEN:?}" "${GH_REPO:?}" "${RUN_ID:?}"
LINEUPS_EVERY_MIN=${LINEUPS_EVERY_MIN:-20}
PIPELINE_EVERY_MIN=${PIPELINE_EVERY_MIN:-180}
now=$(date -u +%s)
started=$(date -u -d "$(gh run view "$RUN_ID" --json createdAt -q .createdAt)" +%s)
last_pipe=$(gh run list -w pipeline.yml -L 20 --json createdAt,status,conclusion \
  -q '[.[] | select(.conclusion != "cancelled" and .conclusion != "skipped")][0].createdAt // empty')
pipe_age=999999
[ -n "$last_pipe" ] && pipe_age=$(( (now - $(date -u -d "$last_pipe" +%s)) / 60 ))
echo "this run started $(( (now - started) / 60 )) min ago; last pipeline ${pipe_age} min ago"
if [ "$pipe_age" -ge "$PIPELINE_EVERY_MIN" ]; then
  echo "dispatching pipeline"; gh workflow run pipeline.yml --ref main; exit 0
fi
wait=$(( LINEUPS_EVERY_MIN * 60 - (now - started) ))
if [ "$wait" -gt 0 ]; then echo "sleeping ${wait}s"; sleep "$wait"; fi
echo "dispatching lineups"; gh workflow run lineups.yml --ref main
