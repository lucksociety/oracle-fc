# Soccer review after the October 30 Discord results

The relevant Discord record is 3–6 across nine issued bets. Website-only selections, changing website lines and informational winner forecasts are excluded. The Espanyol recommendation remains a recorded Discord win; its input defect is still an error requiring correction.

## Supported defects repaired

- `RCD Espanyol de Barcelona` previously matched Barcelona through token containment. Resolve the full club to Espanol, reject a known club when its permitted history is unavailable, remove arbitrary city-token containment, and reject near-tied fuzzy matches. Verified aliases preserve legitimate shortened club names and Understat name variants. Both opponents must resolve to different identities.
- New results, corrected identities and model settings now form an input fingerprint. An updated information set produces a new immutable snapshot even if lineup names and headline version remain unchanged. A distant cached forecast is reused only when the input fingerprint still matches. Earlier records remain untouched.
- Resolution, metadata and the player-context book now obey the same strict fit cutoff as the component models. Future rows cannot influence a replay through team identity or player history.
- Publication rechecks kickoff after context/simulation work. A late fit keeps an earlier frozen prediction when available; it cannot manufacture a post-kickoff forecast or break the rest of the slate.

## Evidence and limits

- All 62 Python regressions pass, plus Discord routing/signature/rendering checks and the prospective/evergreen checks.
- Audited 293 stored source identities. The intentional changed club is Espanyol; legitimate mappings are retained through verified aliases. Understat source names were audited as well, including Borussia M.Gladbach and Clermont Foot.
- Controlled replay: 7,486 top-five-league results strictly before October 30, 2026, using the same published ensemble settings and no live lineup adjustment. The old resolver labels the away side Barcelona and gives it 50.81%; the corrected resolver labels it Espanol and gives it 14.15%. This is a subset-data identity diagnostic, not the exact full-production forecast and not a newly issued pregame pick. Its eventual result is not used for fitting.
- October 30's three selected goal/team-total unders lost; Lille–Lens over 2.5 also lost. The small sample does not establish a new global scoring or tail adjustment. Preserve the previously validated ensemble weights and results-only calibration. No market price enters any prediction.

The ongoing statistical accuracy study may use all prospective forecasts; the user-facing betting record counts only recommendations actually delivered to Discord.
