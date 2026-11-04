import fs from 'node:fs/promises';
import path from 'node:path';
import { loadScan, buildEmbeds, chunkEmbeds } from '../discord/src/worker.js';
const date = process.env.DATE;
if (!/^\d{4}-\d{2}-\d{2}$/.test(date || '')) throw new Error('Invalid date');
const site = 'https://lucksociety.github.io/oracle-fc';
const dates = JSON.parse(await fs.readFile(path.join('data', 'dates', date + '.json'), 'utf8'));
const fallback = dates.fixture_feed_unavailable === true;
const suppressPrices = fallback || process.env.PRICE_STEP_OUTCOME === 'failure';
const net = globalThis.fetch;
globalThis.fetch = async (url, opts) => {
  if (suppressPrices && String(url) === `${site}/data/edge/${date}.json`) return new Response('', { status: 404 });
  if (String(url).startsWith(site + '/data/')) {
    try { return new Response(await fs.readFile(path.join('data', new URL(url).pathname.split('/data/')[1])), { status: 200 }); }
    catch (e) { if (e.code === 'ENOENT') return new Response('', { status: 404 }); throw e; }
  }
  return net(url, opts);
};
const scan = await loadScan(site, date);
if (!scan.hasDates) throw new Error('Model did not produce a date file');
const messages = chunkEmbeds(buildEmbeds(scan, site, { onlyBets: !suppressPrices && process.env.ONLY_BETS === '1' })).map(embeds => ({ embeds }));
if (fallback) {
  messages[0].content = dates.n_forecast
    ? '⚠️ Jupiter fixture feed unavailable. Showing saved pregame forecasts for this date. No bets recommended.'
    : '⚠️ Jupiter fixture feed unavailable. No saved pregame forecasts for this date. No bets recommended.';
}
await fs.mkdir('out', { recursive: true });
await fs.writeFile('out/discord.json', JSON.stringify(messages));
