import assert from 'node:assert/strict';
import {buildEmbeds} from '../src/worker.js';
const fixture={event_id:'f',home_name:'Home',away_name:'Away',competition:'Test',kickoff_utc:'2099-01-01T20:00:00Z'};
const simulation={p_home:.6,p_draw:.2,p_away:.2,xg_home:1.5,xg_away:.8,modal_score:{home:1,away:0,p:.2}};
const scan={date:'2099-01-01',games:[],forecasts:[{fixture,status:'ok',simulation}],hasDates:true,hasEdge:false,nForecast:1};
for(const onlyBets of [false,true]){
 const embeds=buildEmbeds(scan,'https://example.invalid',{onlyBets,now:0});
 assert.equal(embeds.length,2);assert(embeds[1].description.includes('🔮 **'));
 assert(embeds[0].description.includes('score predictions for **1**'));
 if(onlyBets)assert(embeds[0].description.includes('showing available score predictions'));
}
const empty={...scan,nForecast:0,forecasts:[{fixture,status:'unsupported',data_quality:[]} ]};
assert(buildEmbeds(empty,'https://example.invalid',{now:0})[0].description.includes('coverage gap, not a betting pass'));
console.log('Zero qualifying bets retain available predictions, including bets-only fallback; missing coverage is explicit');

const experimental={...scan,forecasts:[{fixture,status:'ok',simulation,forecast_only:true}],games:[{event_id:'f',verdict:'BET',priced_at:'2099-01-01T12:00:00Z',bet:{label:'Must not appear',outcome:{kind:'1x2',res:'H'}}}]};
const card=buildEmbeds(experimental,'https://example.invalid',{now:Date.parse('2099-01-01T12:01:00Z')});
assert(card[1].description.includes('forecast only; competition calibration pending'));assert(!JSON.stringify(card).includes('Must not appear'));
