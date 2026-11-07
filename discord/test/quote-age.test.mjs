import assert from 'node:assert/strict';
import { buildEmbeds } from '../src/worker.js';

const now = Date.parse('2026-11-05T12:00:00Z');
const game = {
  event_id: 'POLY-1', home: 'Home', away: 'Away', kickoff_utc: '2026-11-05T13:00:00Z',
  sim: {modal_score:{home:1,away:0}}, verdict: 'BET', priced_at: '2026-11-05T11:59:00Z',
  bet: { outcome:{kind:'1x2',res:'H'}, label: 'CURRENT_PICK', side: 'YES', model_p: .7, ask: .5, ev_per_dollar: .3 },
};
const scan = { date: '2026-11-05', games: [game], forecasts: [], hasEdge: true };
const render = g => JSON.stringify(buildEmbeds({ ...scan, games: [g], forecasts:[{status:'ok',fixture:{event_id:g.event_id,home_name:g.home,away_name:g.away,kickoff_utc:g.kickoff_utc},simulation:g.sim}] }, 'https://example.test', { now }));
assert(render(game).includes('CURRENT_PICK'));
for (const priced_at of [null, 'invalid', '2026-11-05T12:00:01Z', '2026-11-05T11:54:59Z']) {
  assert(!render({ ...game, priced_at }).includes('CURRENT_PICK'));
}
assert(!render({ ...game, kickoff_utc: '2026-11-05T12:00:00Z', locked: true }).includes('CURRENT_PICK'));
assert.equal(game.verdict, 'BET', 'publishing must preserve the frozen historical record');
console.log('Quote age and kickoff are rechecked before Discord publication');

assert(!render({...game,sim:{modal_score:{home:0,away:1}}}).includes('CURRENT_PICK'));
assert(!render({...game,sim:null}).includes('CURRENT_PICK'));
