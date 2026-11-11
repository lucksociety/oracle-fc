import {test} from 'node:test';import assert from 'node:assert/strict';
import {buildEmbeds} from '../src/worker.js';
test('full-day card includes earlier match, two data gaps and five forecasts',()=>{
 const names=['Vietnam','Wiedenbruck','Wegberg-Beeck','Valladolid','Londrina','Cundinamarca','Quindio','Piratas'];
 const forecasts=names.map((home,i)=>({status:i===0?'not_forecast_before_kickoff':i<3?'unsupported':'ok',
  forecast_only:i>=3,fixture:{event_id:'POLY-'+i,home_name:home,away_name:'Opponent '+i,competition:i===0?'FIFA Friendlies':'Club Friendlies',subcategory:i===0?'fif':'clf',kickoff_utc:i===0?'2026-11-11T12:00:00Z':'2026-11-11T20:00:00Z'},
  ...(i>=3?{simulation:{modal_score:{home:1,away:0,p:.15},top_scores:[],p_home:.6,p_draw:.2,p_away:.2,xg_home:1.5,xg_away:.8}}:{})}));
 const scan={date:'2026-11-11',inventoryScope:'full-day-men-v1',forecasts,games:[],hasDates:true,hasEdge:false,nFixtures:8,nForecast:5};
 const cards=buildEmbeds(scan,'https://example.com',{now:Date.parse('2026-11-11T16:00:00Z')});
 const text=JSON.stringify(cards);
 assert.match(cards[0].description,/\*\*8\*\* games/);
 assert.match(cards[0].description,/5 predictions · 2 data\/coverage gaps · 1 started without/);
 for(const name of names)assert(text.includes(name),name+' must remain visible');
 assert(text.includes('kicked off before one was frozen'));
});
