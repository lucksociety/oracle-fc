import assert from 'node:assert/strict';
import { loadScan, buildEmbeds, chunkEmbeds, allGames } from '../src/worker.js';
const site = 'https://example.invalid';
const size = e => (e.title||'').length+(e.description||'').length+(e.footer?.text||'').length+(e.author?.name||'').length+(e.fields||[]).reduce((s,f)=>s+f.name.length+f.value.length,0);
const originalFetch = globalThis.fetch;
try {
  for (const count of [0, 23, 81]) {
    const date = '2030-10-29';
    const forecasts = Array.from({length:count}, (_,i) => ({
      fixture: {event_id:`f${i}`,home_name:`Home ${i}`,away_name:`Away ${i}`,competition:'Test',kickoff_utc:`${date}T20:00:00Z`},
      status:i%3 ? 'ok' : 'unsupported',
      ...(i%3 ? {simulation:{p_home:.5,p_draw:.2,p_away:.3,xg_home:1.5,xg_away:1,modal_score:{home:1,away:0,p:.15}}}:{}),
    }));
    // Edge and date exports may legitimately contain different sets of fixture IDs.
    const games = [{event_id:'edge-only',home:'Extra Home',away:'Extra Away',competition:'Test',kickoff_utc:`${date}T21:00:00Z`,verdict:'NO BET'}];
    if(count>1) games.push({event_id:'f1',home:'Home 1',away:'Away 1',competition:'Test',verdict:'BET',bet:{label:'Home',side:'yes',ask:.4,model_p:.5,ev_per_dollar:.2}});
    globalThis.fetch = async url => ({ok:true,json:async()=>String(url).includes('/edge/') ? {best_bets:{games}} : String(url).includes('/dates/') ? {n_fixtures:count,forecasts} : null});
    const scan = await loadScan(site,date);
    const rows = allGames(scan);
    assert.equal(rows.length,count+1);
    assert.equal(new Set(rows.map(r=>r.event_id)).size,rows.length);
    const msgs = chunkEmbeds(buildEmbeds(scan,site,{now:0}));
    const text = msgs.flat().map(e=>e.title+'\n'+e.description).join('\n');
    for(const r of rows) assert.ok(text.includes(`${r.home} v ${r.away}`),`missing ${r.event_id}`);
    assert.equal(msgs.flat().filter(e=>e.description?.includes('🔮 **')).length,scan.nForecast);
    assert.ok(msgs.every(m=>m.length<=10 && m.reduce((s,e)=>s+size(e),0)<=6000));
    const bets = buildEmbeds(scan,site,{onlyBets:true,now:0});
    assert.equal(bets.length,count>1 ? 2 : 1);
    console.log(`All ${rows.length} union fixtures rendered within Discord limits`);
  }
} finally { globalThis.fetch = originalFetch; }
