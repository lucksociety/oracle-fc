import {test} from 'node:test';import assert from 'node:assert/strict';
import {allGames,womensFixture} from '../src/worker.js';
test('cached women fixtures cannot appear beside men',()=>{
 assert(womensFixture({subcategory:'uwcl'}));assert(womensFixture({competition:"Women's Champions League"}));
 const scan={forecasts:[{fixture:{event_id:'w',competition:"Women's Champions League"},status:'ok',simulation:{}}],games:[{event_id:'w',competition:"Women's Champions League"},{event_id:'m',competition:'Premier League'}]};
 assert.deepEqual(allGames(scan).map(x=>x.event_id),['m']);
});
