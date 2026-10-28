// Builds the /soccer embeds from the live dashboard data, offline from Discord.
import { loadScan, buildEmbeds, chunkEmbeds } from "../src/worker.js";
const site = "https://lucksociety.github.io/oracle-fc";
for (const d of process.argv.slice(2)) {
  const scan = await loadScan(site, d);
  const embeds = buildEmbeds(scan, site);
  const bets = buildEmbeds(scan, site, { onlyBets: true });
  console.log(d, scan.games.length, "games;", chunkEmbeds(embeds).map((m) => m.length), chunkEmbeds(bets).map((m) => m.length));
  console.log(JSON.stringify(embeds.slice(0, 2), null, 1));
  if (embeds.length > 2) console.log(JSON.stringify(embeds.at(-1), null, 1).slice(0, 1200));
}
