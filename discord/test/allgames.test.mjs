import { loadScan, buildEmbeds, chunkEmbeds, allGames, dailyPayloads } from "../src/worker.js";
const site = "https://lucksociety.github.io/oracle-fc";
const size = (e) => (e.title||"").length+(e.description||"").length+(e.footer?.text||"").length+(e.author?.name||"").length+(e.fields||[]).reduce((s,f)=>s+f.name.length+f.value.length,0);
for (const d of ["2026-10-28","2026-10-29","2026-10-30","2026-10-31"]) {
  const scan = await loadScan(site, d);
  const rows = allGames(scan);
  const msgs = chunkEmbeds(buildEmbeds(scan, site));
  const all = msgs.flat().map((e)=>e.title+"\n"+e.description).join("\n");
  const missing = rows.filter((r) => !all.includes(`${r.home} v ${r.away}`) && !all.includes(`${r.home} ${r.sim?.modal_score?.home}`));
  const fcEmb = msgs.flat().filter((e) => e.description?.includes("🔮 **")).length;
  console.log(d, "fixtures file", scan.nFixtures, "ok", scan.nForecast, "| rows", rows.length, "score embeds", fcEmb, "| msgs", msgs.map((m)=>`${m.length}e/${m.reduce((s,e)=>s+size(e),0)}c`).join(" "), "missing", missing.length, "bets", rows.filter(r=>r.g?.verdict==="BET").length);
  if (fcEmb !== scan.nForecast || missing.length || msgs.some((m)=>m.length>10 || m.reduce((s,e)=>s+size(e),0)>6000) || rows.length !== Math.max(scan.nFixtures, scan.games.length)) { console.log("FAIL"); process.exitCode = 1; }
}
const b = buildEmbeds(await loadScan(site, "2026-10-29"), site, { onlyBets: true });
console.log("onlyBets embeds", b.length);
