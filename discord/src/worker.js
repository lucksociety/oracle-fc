// ORACLE FC · Discord /soccer interactions endpoint (Cloudflare Worker).
// Relays the post-hoc Best Bets that the ORACLE FC pipeline publishes to GitHub Pages.
// The Worker never feeds prices into the model; it only reads the published snapshot.
//
// Vars:    DISCORD_APPLICATION_ID, DISCORD_PUBLIC_KEY (public, not secret), SITE_URL (optional)
// Secrets: DISCORD_BOT_TOKEN, used only by the daily scheduled post (slash-command replies use the
//          interaction token). Var SOCCER_CHANNEL_ID = the #soccer-bets channel.

const DEFAULT_SITE = "https://lucksociety.github.io/oracle-fc";
const API = "https://discord.com/api/v10";
const TZ = "America/New_York";
const COLORS = { gold: 0xd69c08, goldBright: 0xf9d731, green: 0x026016, greenBright: 0x5b9868, border: 0x50461e, danger: 0xd9534f };
const EPHEMERAL = 1 << 6;

// ------------------------------------------------------------------ signature verification
function hexToBytes(hex) {
  if (!hex || hex.length % 2) return new Uint8Array();
  const out = new Uint8Array(hex.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(hex.substr(i * 2, 2), 16);
  return out;
}
let KEY_CACHE = null;
async function verifyDiscord(request, publicKey) {
  const sig = request.headers.get("X-Signature-Ed25519");
  const ts = request.headers.get("X-Signature-Timestamp");
  const body = await request.text();
  if (!sig || !ts) return { ok: false, body };
  try {
    if (!KEY_CACHE || KEY_CACHE.hex !== publicKey) {
      KEY_CACHE = { hex: publicKey, key: await crypto.subtle.importKey("raw", hexToBytes(publicKey), { name: "Ed25519" }, false, ["verify"]) };
    }
    const ok = await crypto.subtle.verify({ name: "Ed25519" }, KEY_CACHE.key, hexToBytes(sig), new TextEncoder().encode(ts + body));
    return { ok, body };
  } catch (_) {
    return { ok: false, body };
  }
}
const json = (obj, status = 200) => new Response(JSON.stringify(obj), { status, headers: { "content-type": "application/json" } });

// ------------------------------------------------------------------ dates
export function todayET(now = new Date()) {
  return new Intl.DateTimeFormat("en-CA", { timeZone: TZ }).format(now);
}
function addDays(ymd, n) {
  const d = new Date(ymd + "T12:00:00Z");
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}
export function parseDate(input, now = new Date()) {
  const today = todayET(now);
  const s = String(input ?? "").trim().toLowerCase();
  if (!s || s === "today") return today;
  if (s === "tomorrow" || s === "tmrw") return addDays(today, 1);
  if (s === "yesterday") return addDays(today, -1);
  let m = s.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
  let y, mo, d;
  if (m) [y, mo, d] = [+m[1], +m[2], +m[3]];
  else if ((m = s.match(/^(\d{1,2})[-/.](\d{1,2})(?:[-/.](\d{2,4}))?$/))) {
    [mo, d] = [+m[1], +m[2]];
    y = m[3] ? (m[3].length === 2 ? 2000 + +m[3] : +m[3]) : +today.slice(0, 4);
  } else return null;
  const iso = `${y}-${String(mo).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
  const chk = new Date(iso + "T12:00:00Z");
  if (isNaN(chk) || chk.toISOString().slice(0, 10) !== iso) return null;
  return iso;
}
export function dateChoices(now = new Date()) {
  const today = todayET(now);
  const out = [];
  for (let n = -1; n <= 7; n++) {
    const ymd = addDays(today, n);
    const d = new Date(ymd + "T12:00:00Z");
    const dow = d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", timeZone: "UTC" });
    const tag = n === 0 ? " (today)" : n === 1 ? " (tomorrow)" : n === -1 ? " (yesterday)" : "";
    out.push({ name: dow + tag, value: ymd });
  }
  return out;
}
const unix = (iso) => (iso ? Math.floor(new Date(iso).getTime() / 1000) : null);

// ------------------------------------------------------------------ data
async function getJSON(url) {
  const r = await fetch(url, { cf: { cacheTtl: 120, cacheEverything: true }, headers: { "user-agent": "oracle-fc-discord/1.0" } });
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`${r.status} fetching ${url}`);
  return r.json();
}
export function gamesFromEdge(edge) {
  if (edge?.best_bets?.games?.length) return edge.best_bets.games;
  return (edge?.events || []).map((e) => {
    const bb = e.best_bet || {};
    const g = { event_id: e.event_id, home: e.home, away: e.away, competition: e.competition, kickoff_utc: e.kickoff_utc, ...bb };
    if (!e.best_bet) Object.assign(g, { verdict: "NO BET", reason: e.market_after_kickoff ? "prices captured after kick-off (in-play)" : "no Jupiter prices captured for this game" });
    else if (e.market_after_kickoff && bb.verdict === "BET") Object.assign(g, { verdict: "NO BET", reason: "prices captured after kick-off (in-play)", bet: undefined });
    return g;
  });
}
// Model version that produced the bets: the newest version among the games' frozen forecasts.
export function modelVersionOf(games, dates, edge) {
  const vs = [...new Set((games || []).map((g) => g.model_version).filter(Boolean))];
  const semver = (v) => (String(v).match(/^(\d+)\.(\d+)\.(\d+)/) || [0, 0, 0, 0]).slice(1).map(Number);
  vs.sort((a, b) => { const x = semver(a), y = semver(b); return x[0] - y[0] || x[1] - y[1] || x[2] - y[2]; });
  return vs.at(-1) || dates?.model_version || edge?.events?.[0]?.model_version || null;
}
export async function loadScan(site, date) {
  const [edge, dates, results, record] = await Promise.all([
    getJSON(`${site}/data/edge/${date}.json`),
    getJSON(`${site}/data/dates/${date}.json`).catch(() => null),
    getJSON(`${site}/data/results/${date}.json`).catch(() => null),
    getJSON(`${site}/data/results/record.json`).catch(() => null),
  ]);
  const forecasts = dates?.forecasts || [];
  const games = edge ? gamesFromEdge(edge) : [];
  const graded = new Map((results?.games || []).map((g) => [g.event_id, g]));
  for (const g of games) {
    const r = graded.get(g.event_id);
    if (r) g.graded = { status: r.status, score: r.result?.score_90 || null, bet_result: r.bet_result || null, pnl: r.pnl_units ?? null };
  }
  return {
    date,
    games,
    fetchedAt: edge?.market_fetched_at || null,
    nFixtures: dates?.n_fixtures ?? forecasts.length,
    nForecast: forecasts.filter((f) => f.status === "ok").length,
    modelVersion: modelVersionOf(games, dates, edge),
    results: results?.summary || null,
    record: record?.overall || null,
    recordSince: record?.by_day?.[0]?.date || null,
    hasEdge: !!edge,
    hasDates: !!dates,
    forecasts,
  };
}

// ------------------------------------------------------------------ formatting
const pct = (x, d = 1) => (x == null ? "–" : (100 * x).toFixed(d) + "%");
const cents = (x) => (x == null ? "–" : (100 * x).toFixed(1).replace(/\.0$/, "") + "¢");
const evp = (x) => (x == null ? "–" : (x >= 0 ? "+" : "") + (100 * x).toFixed(1) + "%");
const pp = (x) => (x == null ? "–" : (x >= 0 ? "+" : "") + Number(x).toFixed(1) + " pp");
const units = (u) => (u == null ? "–" : `${u >= 0 ? "+" : ""}${Number(u).toFixed(2)}u`);
const clip = (s, n) => (String(s).length > n ? String(s).slice(0, n - 1) + "…" : String(s));

// Every fixture on the date: union of data/dates forecasts (incl. unsupported / not forecast) and edge games.
const STATUS_WHY = {
  unsupported: "no forecast: competition not covered by the model's data",
  not_forecast_before_kickoff: "no forecast: kicked off before one was frozen",
};
export function allGames(scan) {
  const byId = new Map(scan.games.map((g) => [g.event_id, g]));
  const rows = new Map();
  for (const f of scan.forecasts || []) {
    const fx = f.fixture || {};
    const id = fx.event_id;
    if (!id) continue;
    const ok = f.status === "ok" && f.simulation;
    rows.set(id, { event_id: id, home: fx.home_name || fx.home, away: fx.away_name || fx.away, competition: fx.competition,
      kickoff_utc: fx.kickoff_utc, sim: ok ? f.simulation : null,
      why: ok ? null : STATUS_WHY[f.status] || `no forecast (${f.status || "unknown"})`, g: byId.get(id) || null });
  }
  for (const g of scan.games) if (!rows.has(g.event_id)) {
    rows.set(g.event_id, { event_id: g.event_id, home: g.home, away: g.away, competition: g.competition, kickoff_utc: g.kickoff_utc,
      sim: null, why: "forecast not in the published date file", g });
  }
  return [...rows.values()].sort((x, y) => (x.kickoff_utc || "").localeCompare(y.kickoff_utc || "") || String(x.home).localeCompare(String(y.home)));
}
export const koET = (iso) => (iso ? new Intl.DateTimeFormat("en-US", { timeZone: TZ, weekday: "short", hour: "numeric", minute: "2-digit" }).format(new Date(iso)) + " ET" : "");
const isBet = (g) => !!g && g.verdict === "BET" && !!g.bet;
const sc = (s) => `${s.home}–${s.away}`;
function pickText(g) {
  if (isBet(g)) {
    const b = g.bet;
    return `**BET** 🍀 ${clip(b.label, 90)} (buy ${b.side}) @ ${cents(b.ask)} · model ${pct(b.model_p)} · EV ${evp(b.ev_per_dollar)}${g.locked ? " 🔒" : ""}`;
  }
  if (!g) return "**NO BET** · no Jupiter prices for this game";
  const c = g.closest;
  return `**NO BET** · ${c ? `closest: ${clip(c.label, 60)} (P ${pct(c.model_p)}, ask ${cents(c.ask)}, EV ${evp(c.ev_per_dollar)})` : clip(g.reason || "no side with model P > 50% and +EV at the ask", 120)}`;
}
function resultText(r) {
  const res = r.g?.graded;
  if (res?.status !== "final") return null;
  return `FT **${res.score ?? "?"}**${res.bet_result ? ` · **${res.bet_result}** ${res.bet_result === "WIN" ? "✅" : "❌"} ${units(res.pnl)}` : ""}`;
}
export function gameEmbed(r, now = Date.now()) {
  const ko = unix(r.kickoff_utc);
  const s = r.sim, g = r.g, res = g?.graded;
  const lines = [`${clip(r.competition || "", 80)}${ko ? ` · **${koET(r.kickoff_utc)}** (<t:${ko}:R>)` : ""}`];
  if (s) {
    const top = (s.top_scores || []).slice(1, 4).map((t) => `${sc(t)} ${pct(t.p, 0)}`).join(", ");
    lines.push(`🔮 **${s.modal_score ? sc(s.modal_score) : "?"}**${s.modal_score?.p != null ? ` (${pct(s.modal_score.p)})` : ""}${top ? ` · next: ${top}` : ""}`);
    lines.push(`H/D/A **${pct(s.p_home, 0)} / ${pct(s.p_draw, 0)} / ${pct(s.p_away, 0)}** · xG ${Number(s.xg_home).toFixed(2)}–${Number(s.xg_away).toFixed(2)}`);
  } else lines.push(`🔮 ${r.why}`);
  lines.push(pickText(g));
  const rt = resultText(r);
  if (rt) lines.push(rt);
  else if (g?.locked) lines.push(`🔒 locked at the pre-kick-off price (${String(g.locked_from_snapshot || "").slice(11, 16)} UTC)`);
  const icon = res?.bet_result === "WIN" ? "✅" : res?.bet_result === "LOSS" ? "❌" : isBet(g) ? "🍀" : "⚽";
  return {
    color: res?.bet_result === "WIN" ? COLORS.greenBright : res?.bet_result === "LOSS" ? COLORS.danger : isBet(g) ? COLORS.gold : COLORS.border,
    title: clip(`${icon} ${r.home} v ${r.away}`, 256),
    description: clip(lines.join("\n"), 1000),
  };
}
// Games without a forecast are listed compactly (they can't have a score prediction or a bet).
function unforecastEmbeds(rows) {
  const groups = []; let cur = [], len = 0;
  for (const r of rows) {
    const ko = unix(r.kickoff_utc);
    const line = clip(`**${r.home} v ${r.away}**${ko ? ` · ${koET(r.kickoff_utc)}` : ""} · ${r.competition || ""}${resultText(r) ? ` · ${resultText(r)}` : ""}\n> **NO BET** · ${r.why}`, 300);
    if (cur.length && len + line.length + 1 > 3800) { groups.push(cur); cur = []; len = 0; }
    cur.push(line); len += line.length + 1;
  }
  if (cur.length) groups.push(cur);
  return groups.map((lines, i) => ({
    color: COLORS.border,
    title: `📋 No forecast · NO BET${groups.length > 1 ? ` (${i + 1}/${groups.length})` : ""}`,
    description: lines.join("\n"),
  }));
}

export function buildEmbeds(scan, site, opts = {}) {
  const dash = `${site}/?date=${scan.date}`;
  const now = opts.now ?? Date.now();
  const onlyBets = opts.onlyBets === true; // default: every game
  const rows = allGames(scan).map((r) => ({ ...r, g: r.g ? { ...r.g, started: !!r.kickoff_utc && new Date(r.kickoff_utc).getTime() <= now } : null }));
  const games = rows.map((r) => r.g).filter(Boolean);
  const bets = rows.filter((r) => isBet(r.g));
  const nobets = rows.filter((r) => !isBet(r.g));
  const lines = summaryLines(scan, games, rows, bets, nobets, { ...opts, onlyBets });
  const summary = {
    color: COLORS.goldBright,
    author: { name: "ORACLE FC · Luck Society", url: site + "/", icon_url: `${site}/assets/logo.jpg` },
    title: `⚽ Best Bets · ${scan.date}`,
    url: dash, // only the summary carries the url, so Discord never merges the game embeds
    description: lines.join("\n"),
    thumbnail: { url: `${site}/assets/logo.jpg` },
    footer: { text: `${dash.replace(/^https?:\/\//, "")}${scan.modelVersion ? ` · model ${scan.modelVersion}` : ""}` },
  };
  const shown = onlyBets ? bets : rows;
  return [summary, ...shown.filter((r) => r.sim || isBet(r.g)).map((r) => gameEmbed(r, now)),
    ...unforecastEmbeds(shown.filter((r) => !r.sim && !isBet(r.g)))];
}

function summaryLines(scan, games, rows, bets, nobets, opts) {
  const lines = [];
  const nFc = rows.filter((r) => r.sim).length;
  if (!scan.hasEdge && !rows.length) {
    lines.push(scan.hasDates
      ? `Forecasts are frozen for **${scan.nForecast}** games, but the pipeline hasn't captured Jupiter prices for ${scan.date} yet, so there are no picks. It snapshots every 3 hours, or open the dashboard and hit **Fetch live Jupiter prices now**.`
      : `No ORACLE FC scan stored for **${scan.date}**. The pipeline covers today to +7 days, because Jupiter only lists upcoming games.`);
  } else {
    lines.push(`**${rows.length}** games · **${bets.length}** bet · **${nobets.length}** NO BET · score predictions for **${nFc}**${rows.length > nFc ? ` (${rows.length - nFc} not forecast)` : ""}`);
    if (!scan.hasEdge) lines.push("Jupiter prices not captured yet for this date, so every game is NO BET for now.");
    if (scan.fetchedAt) lines.push(`Prices: Jupiter snapshot <t:${unix(scan.fetchedAt)}:f> (<t:${unix(scan.fetchedAt)}:R>)`);
    if (scan.modelVersion) lines.push(`Model: **${scan.modelVersion}**`);
    const locked = games.filter((g) => g.started && g.locked).length;
    const stale = games.filter((g) => g.started && !g.locked && g.graded?.status !== "final").length;
    if (locked) lines.push(`🔒 ${locked} game(s) kicked off; their picks are locked at the last pre-kick-off price.`);
    if (stale) lines.push(`⏱️ ${stale} game(s) already kicked off without a pre-kick-off lock.`);
    const day = scan.results;
    if (day && day.bets && (day.bets.wins + day.bets.losses) > 0) lines.push(`📊 ${scan.date} graded: bets **${day.bets.wins}-${day.bets.losses}** · **${units(day.bets.units)}** (${day.n_final}/${day.n_games} final)`);
    if (opts.onlyBets && nobets.length) lines.push(`_Showing bets only (only_bets: true); ${nobets.length} NO BET games hidden._`);
  }
  const rec = scan.record?.bets;
  if (rec && (rec.wins + rec.losses) > 0) lines.push(`📒 Running record${scan.recordSince ? ` since ${scan.recordSince}` : ""}: **${rec.wins}-${rec.losses}** · **${units(rec.units)}** · ROI ${rec.roi == null ? "–" : (100 * rec.roi).toFixed(1) + "%"} (1u per bet at ask + fees)`);
  lines.push("", "Rule: model P > 50% **and** +EV buying at the Jupiter ask incl. fees; highest EV per game. Prices are compared only *after* each forecast is frozen and never feed the model. Research, not financial advice.");
  return lines;
}

// Discord allows at most 10 embeds and 6000 embed characters per message.
function embedSize(e) {
  const fields = (e.fields || []).reduce((s, f) => s + f.name.length + f.value.length, 0);
  return (e.title || "").length + (e.description || "").length + (e.footer?.text || "").length + (e.author?.name || "").length + fields;
}
export function chunkEmbeds(embeds) {
  const msgs = [];
  let cur = [], size = 0;
  for (const e of embeds) {
    const n = embedSize(e);
    if (cur.length && (cur.length >= 10 || size + n > 5800)) { msgs.push(cur); cur = []; size = 0; }
    cur.push(e); size += n;
  }
  if (cur.length) msgs.push(cur);
  return msgs;
}

// ------------------------------------------------------------------ Discord follow-ups
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function discordCall(method, url, payload, tries = 4, headers = { "content-type": "application/json" }) {
  for (let i = 0; i < tries; i++) {
    const r = await fetch(url, { method, headers, body: JSON.stringify(payload) });
    if (r.status === 429) {
      const j = await r.json().catch(() => ({}));
      await sleep(Math.ceil((j.retry_after || 1) * 1000) + 100);
      continue;
    }
    if (!r.ok) throw new Error(`Discord ${method} ${r.status}: ${(await r.text()).slice(0, 300)}`);
    return r;
  }
  throw new Error("Discord rate limit: gave up");
}
const linkRow = (dash) => [{ type: 1, components: [{ type: 2, style: 5, label: "Open ORACLE FC dashboard", url: dash }] }];

export async function runSoccer(interaction, env) {
  const site = (env.SITE_URL || DEFAULT_SITE).replace(/\/$/, "");
  const appId = env.DISCORD_APPLICATION_ID || interaction.application_id;
  const hook = `${API}/webhooks/${appId}/${interaction.token}`;
  const opts = Object.fromEntries((interaction.data.options || []).map((o) => [o.name, o.value]));
  const date = parseDate(opts.date);
  const editOriginal = (payload) => discordCall("PATCH", hook + "/messages/@original", payload);
  try {
    if (!date) {
      const bad = clip(String(opts.date).replace(/[`*_~|]/g, ""), 40);
      await editOriginal({ content: "Couldn't read '" + bad + "' as a date. Try 2026-10-31, 10/31, today or tomorrow." });
      return;
    }
    const scan = await loadScan(site, date);
    const msgs = chunkEmbeds(buildEmbeds(scan, site, { onlyBets: opts.only_bets === true }));
    const dash = `${site}/?date=${date}`;
    for (let i = 0; i < msgs.length; i++) {
      const payload = { embeds: msgs[i], allowed_mentions: { parse: [] } };
      if (i === msgs.length - 1) payload.components = linkRow(dash);
      if (i === 0) await editOriginal(payload);
      else { await sleep(400); await discordCall("POST", hook, payload); }
    }
  } catch (err) {
    console.log("soccer command error", String(err));
    await notifyFailure(editOriginal, err);
  }
}

// ------------------------------------------------------------------ daily scheduled post
// Cron runs at 13:00 and 14:00 UTC; only the one that lands at 09:xx America/New_York posts
// (EDT = UTC-4 -> 13:00, EST = UTC-5 -> 14:00), so DST is handled year-round.
export function etHour(d = new Date()) {
  return +new Intl.DateTimeFormat("en-US", { timeZone: TZ, hour: "numeric", hourCycle: "h23" }).format(d);
}
export function dailyPayloads(scan, site) {
  const dash = `${site}/?date=${scan.date}`;
  const msgs = chunkEmbeds(buildEmbeds(scan, site));
  return msgs.map((embeds, i) => ({ embeds, allowed_mentions: { parse: [] }, ...(i === msgs.length - 1 ? { components: linkRow(dash) } : {}) }));
}
const botHeaders = (env) => ({ authorization: `Bot ${env.DISCORD_BOT_TOKEN}`, "content-type": "application/json", "user-agent": "oracle-fc-discord (https://github.com/lucksociety/oracle-fc, 1.1)" });
async function alreadyPosted(env, channel, date) {
  // dedupe (cron retries / manual re-runs): skip if this bot already posted today's report
  const r = await fetch(`${API}/channels/${channel}/messages?limit=50`, { headers: botHeaders(env) });
  if (!r.ok) throw new Error(`Discord read ${r.status}: ${(await r.text()).slice(0, 200)}`);
  const appId = env.DISCORD_APPLICATION_ID;
  return (await r.json()).some((m) => m.author?.id === appId && (m.embeds || []).some((e) => e.title === `⚽ Best Bets · ${date}`));
}
export async function dailyPost(env, when = new Date(), { force = false } = {}) {
  const site = (env.SITE_URL || DEFAULT_SITE).replace(/\/$/, "");
  const channel = env.SOCCER_CHANNEL_ID;
  if (!channel || !env.DISCORD_BOT_TOKEN) { console.log("daily post: SOCCER_CHANNEL_ID or DISCORD_BOT_TOKEN missing"); return { posted: false, reason: "not configured" }; }
  if (!force && etHour(when) !== 9) return { posted: false, reason: `ET hour is ${etHour(when)}, not 9` };
  const date = todayET(when);
  if (await alreadyPosted(env, channel, date)) { console.log("daily post: already posted", date); return { posted: false, reason: "already posted" }; }
  const scan = await loadScan(site, date);
  const payloads = dailyPayloads(scan, site);
  for (let i = 0; i < payloads.length; i++) {
    if (i) await sleep(700);
    await discordCall("POST", `${API}/channels/${channel}/messages`, payloads[i], 4, botHeaders(env));
  }
  console.log("daily post: posted", date, payloads.length, "messages");
  return { posted: true, date, messages: payloads.length };
}

async function notifyFailure(edit, err) {
  try {
    await edit({ content: "ORACLE FC scan error: " + clip(err && err.message, 300) });
  } catch (_) {
    // interaction already gone; nothing else to do
  }
}

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(dailyPost(env, new Date(event.scheduledTime)).catch((e) => console.log("daily post error", String(e))));
  },
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (request.method === "GET") {
      if (url.pathname === "/health") return json({ ok: true, today_et: todayET() });
      if (url.pathname === "/daily-preview") {
        // DRY RUN of the 09:00 ET post: returns the exact payloads, posts nothing
        const at = url.searchParams.get("at") ? new Date(url.searchParams.get("at")) : new Date();
        if (isNaN(at)) return json({ error: "bad at" }, 400);
        const site = (env.SITE_URL || DEFAULT_SITE).replace(/\/$/, "");
        const date = todayET(at);
        const payloads = dailyPayloads(await loadScan(site, date), site);
        return json({ dry_run: true, would_post_at_this_time: etHour(at) === 9, et_hour: etHour(at), date,
          channel_id: env.SOCCER_CHANNEL_ID || null, bot_token_configured: !!env.DISCORD_BOT_TOKEN,
          crons_utc: ["0 13 * * *", "0 14 * * *"], n_messages: payloads.length, payloads });
      }
      if (url.pathname === "/scan") {
        // public read-only summary of what /soccer would show (same published data)
        const date = parseDate(url.searchParams.get("date"));
        if (!date) return json({ error: "bad date" }, 400);
        const scan = await loadScan((env.SITE_URL || DEFAULT_SITE).replace(/\/$/, ""), date);
        const rows = allGames(scan);
        const bets = rows.filter((r) => isBet(r.g));
        return json({ date, model_version: scan.modelVersion, prices_at: scan.fetchedAt, n_games: rows.length,
          n_fixtures_file: scan.nFixtures, n_forecast_file: scan.nForecast, n_score_predictions: rows.filter((r) => r.sim).length,
          n_bet: bets.length, n_no_bet: rows.length - bets.length, n_locked: scan.games.filter((g) => g.locked).length,
          embeds_per_message: chunkEmbeds(buildEmbeds(scan, (env.SITE_URL || DEFAULT_SITE).replace(/\/$/, ""))).map((m) => m.length),
          games: rows.map((r) => ({ match: `${r.home} v ${r.away}`, kickoff_utc: r.kickoff_utc,
            modal_score: r.sim?.modal_score ? `${r.sim.modal_score.home}-${r.sim.modal_score.away}` : null,
            p_hda: r.sim ? [r.sim.p_home, r.sim.p_draw, r.sim.p_away] : null, xg: r.sim ? [r.sim.xg_home, r.sim.xg_away] : null,
            pick: isBet(r.g) ? r.g.bet.label : "NO BET", ask: isBet(r.g) ? r.g.bet.ask : null, ev: isBet(r.g) ? r.g.bet.ev_per_dollar : null,
            locked: !!r.g?.locked, result: r.g?.graded?.bet_result || null, note: r.why })),
          day: scan.results?.bets || null, record: scan.record?.bets || null });
      }
      return new Response("ORACLE FC Discord interactions endpoint. POST only.");
    }
    if (request.method !== "POST") return new Response("Method not allowed", { status: 405 });
    const { ok, body } = await verifyDiscord(request, env.DISCORD_PUBLIC_KEY);
    if (!ok) return new Response("invalid request signature", { status: 401 });
    const i = JSON.parse(body);
    if (i.type === 1) return json({ type: 1 }); // PING -> PONG
    if (i.type === 4) return json({ type: 8, data: { choices: dateChoices() } }); // date picker
    if (i.type === 2 && i.data?.name === "soccer") {
      ctx.waitUntil(runSoccer(i, env));
      return json({ type: 5 }); // deferred reply, follow-ups carry the embeds
    }
    return json({ type: 4, data: { content: "Unknown command.", flags: EPHEMERAL } });
  },
};
