import fs from 'node:fs/promises';
import path from 'node:path';
import { loadScan, buildEmbeds, chunkEmbeds } from '../discord/src/worker.js';
const date = process.env.DATE;
if (!/^\d{4}-\d{2}-\d{2}$/.test(date || '')) throw new Error('Invalid date');
const site = 'https://lucksociety.github.io/oracle-fc';
const net = globalThis.fetch;
globalThis.fetch = async (url, opts) => {
  if (String(url).startsWith(site + '/data/')) {
    try { return new Response(await fs.readFile(path.join('data', new URL(url).pathname.split('/data/')[1])), { status: 200 }); }
    catch (e) { if (e.code === 'ENOENT') return new Response('', { status: 404 }); throw e; }
  }
  return net(url, opts);
};
const scan = await loadScan(site, date);
if (!scan.hasDates) throw new Error('Model did not produce a date file');
const messages = chunkEmbeds(buildEmbeds(scan, site, { onlyBets: process.env.ONLY_BETS === '1' })).map(embeds => ({ embeds }));
await fs.mkdir('out', { recursive: true });
await fs.writeFile('out/discord.json', JSON.stringify(messages));
