// ORACLE FC · Discord /soccer interactions endpoint (Cloudflare Worker).
// Relays the post-hoc Best Bets that the ORACLE FC pipeline publishes to GitHub Pages.
// The Worker never feeds prices into the model; it only reads the published snapshot.
//
// Vars:    DISCORD_APPLICATION_ID, DISCORD_PUBLIC_KEY (public, not secret), SITE_URL (optional)
// Secrets: none required. Replies use the interaction token, so the bot token never lives here.

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
export async function loadScan(site, date) {
  const [edge, dates] = await Promise.all([
    getJSON(`${site}/data/edge/${date}.json`),
    getJSON(`${site}/data/dates/${date}.json`).catch(() => null),
  ]);
  const forecasts = dates?.forecasts || [];
  return {
    date,
    games: edge ? gamesFromEdge(edge) : [],
    fetchedAt: edge?.market_fetched_at || null,
    nFixtures: dates?.n_fixtures ?? forecasts.length,
    nForecast: forecasts.filter((f) => f.status === "ok").length,
    modelVersion: dates?.model_version || edge?.events?.[0]?.model_version || null,
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
const clip = (s, n) => (String(s).length > n ? String(s).slice(0, n - 1) + "…" : String(s));

function betEmbed(g, dash) {
  const b = g.bet;
  const ko = unix(g.kickoff_utc);
  const flags = [
    b.thin_book ? "⚠️ thin book" : null,
    b.volume != null ? `vol ${Number(b.volume).toLocaleString("en-US")}` : null,
    b.fee_assumed ? "fee assumed" : null,
    g.started ? "⏱️ already kicked off" : null,
  ].filter(Boolean).join(" · ");
  return {
    color: COLORS.gold,
    title: clip(`🍀 ${g.home} v ${g.away}`, 256),
    url: dash,
    description: `**${clip(b.label, 200)}** · buy **${b.side}**\n${g.competition || ""}${ko ? ` · <t:${ko}:f>` : ""}`,
    fields: [
      { name: "Price (ask)", value: cents(b.ask), inline: true },
      { name: "Model", value: pct(b.model_p), inline: true },
      { name: "EV / $1", value: evp(b.ev_per_dollar), inline: true },
      { name: "Edge", value: pp(b.edge_pp), inline: true },
      { name: "Cost incl. fee", value: cents(b.cost_per_contract), inline: true },
      { name: "Eligible sides", value: `${g.n_eligible ?? "?"} of ${g.n_priced ?? "?"}`, inline: true },
    ],
    ...(flags ? { footer: { text: flags } } : {}),
  };
}
function noBetLine(g) {
  const ko = unix(g.kickoff_utc);
  const c = g.closest;
  const why = c
    ? `closest: ${c.label} (P ${pct(c.model_p)}, ask ${cents(c.ask)}, EV ${evp(c.ev_per_dollar)})`
    : g.reason || "no side with model P > 50% and +EV at the ask";
  return `**${g.home} v ${g.away}**${ko ? ` · <t:${ko}:t>` : ""}\n> NO BET · ${why}`;
}
function noBetEmbeds(games, dash) {
  const groups = [];
  let cur = [], len = 0;
  for (const g of games) {
    const line = clip(noBetLine(g), 400);
    if (cur.length && len + line.length + 1 > 3500) { groups.push(cur); cur = []; len = 0; }
    cur.push(line); len += line.length + 1;
  }
  if (cur.length) groups.push(cur);
  return groups.map((lines, i) => ({
    color: COLORS.border,
    title: `🚫 No bet${groups.length > 1 ? ` (${i + 1}/${groups.length})` : ""}`,
    url: dash,
    description: lines.join("\n"),
  }));
}

function scoreLine(f, g) {
  const fx = f.fixture || {}, sm = f.simulation || {};
  const ko = unix(fx.kickoff_utc);
  const m = sm.modal_score;
  const home = fx.home_name || fx.home, away = fx.away_name || fx.away;
  let pick = "NO BET";
  if (g && g.verdict === "BET" && g.bet) pick = `🍀 ${clip(g.bet.label, 60)} (${g.bet.side}) @ ${cents(g.bet.ask)} · EV ${evp(g.bet.ev_per_dollar)}`;
  else if (!g) pick = "NO BET (no prices)";
  return `**${home} ${m ? m.home + "–" + m.away : "?"} ${away}**${ko ? ` · <t:${ko}:t>` : ""}\n> ${pct(sm.p_home, 0)}/${pct(sm.p_draw, 0)}/${pct(sm.p_away, 0)} · xG ${Number(sm.xg_home).toFixed(2)}–${Number(sm.xg_away).toFixed(2)} · ${pick}`;
}
function scoreEmbeds(scan, games, dash) {
  const byId = new Map(games.map((g) => [g.event_id, g]));
  const fs = (scan.forecasts || []).filter((f) => f.status === "ok" && f.simulation)
    .sort((a, b) => (a.fixture?.kickoff_utc || "").localeCompare(b.fixture?.kickoff_utc || ""));
  const groups = []; let cur = [], len = 0;
  for (const f of fs) {
    const line = clip(scoreLine(f, byId.get(f.fixture?.event_id)), 400);
    if (cur.length && len + line.length + 1 > 3500) { groups.push(cur); cur = []; len = 0; }
    cur.push(line); len += line.length + 1;
  }
  if (cur.length) groups.push(cur);
  return groups.map((lines, i) => ({
    color: COLORS.goldBright,
    title: `🔮 Score predictions${groups.length > 1 ? ` (${i + 1}/${groups.length})` : ""}`,
    url: dash,
    description: lines.join("\n"),
    ...(i === groups.length - 1 ? { footer: { text: "Most likely exact score · home/draw/away · expected goals · best bet" } } : {}),
  }));
}

export function buildEmbeds(scan, site, opts = {}) {
  const dash = `${site}/?date=${scan.date}`;
  const now = opts.now ?? Date.now();
  const games = scan.games.map((g) => ({ ...g, started: !!g.kickoff_utc && new Date(g.kickoff_utc).getTime() <= now }));
  const isBet = (g) => g.verdict === "BET" && g.bet;
  const bets = games.filter(isBet).sort((a, b) => b.bet.ev_per_dollar - a.bet.ev_per_dollar);
  const nobets = games.filter((g) => !isBet(g)).sort((a, b) => (a.kickoff_utc || "").localeCompare(b.kickoff_utc || ""));
  const lines = summaryLines(scan, games, bets, nobets, opts);
  const summary = {
    color: COLORS.goldBright,
    author: { name: "ORACLE FC · Luck Society", url: site + "/", icon_url: `${site}/assets/logo.jpg` },
    title: `⚽ Best Bets · ${scan.date}`,
    url: dash,
    description: lines.join("\n"),
    thumbnail: { url: `${site}/assets/logo.jpg` },
    footer: { text: `${dash.replace(/^https?:\/\//, "")}${scan.modelVersion ? ` · model ${scan.modelVersion}` : ""}` },
  };
  const embeds = [summary, ...bets.map((g) => betEmbed(g, dash))];
  if (!opts.onlyBets) embeds.push(...scoreEmbeds(scan, games, dash));
  return embeds;
}

function summaryLines(scan, games, bets, nobets, opts) {
  const lines = [];
  if (!scan.hasEdge) {
    lines.push(scan.hasDates
      ? `Forecasts are frozen for **${scan.nForecast}** games, but the pipeline hasn't captured Jupiter prices for ${scan.date} yet, so there are no picks. It snapshots every 3 hours, or open the dashboard and hit **Fetch live Jupiter prices now**.`
      : `No ORACLE FC scan stored for **${scan.date}**. The pipeline covers today to +7 days, because Jupiter only lists upcoming games.`);
  } else {
    const nf = scan.nFixtures || games.length;
    const unforecast = scan.nForecast && scan.nForecast < nf ? ` (${nf - scan.nForecast} not forecast)` : "";
    lines.push(`**${bets.length}** bet · **${nobets.length}** no bet · ${nf} Jupiter games${unforecast}`);
    if (scan.fetchedAt) lines.push(`Prices: Jupiter snapshot <t:${unix(scan.fetchedAt)}:f> (<t:${unix(scan.fetchedAt)}:R>)`);
    const started = games.filter((g) => g.started).length;
    if (started) lines.push(`⏱️ ${started} game(s) already kicked off; those prices are stale.`);
    if (opts.onlyBets && nobets.length) lines.push(`_Showing bets only; ${nobets.length} NO BET games hidden._`);
  }
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
async function discordCall(method, url, payload, tries = 4) {
  for (let i = 0; i < tries; i++) {
    const r = await fetch(url, { method, headers: { "content-type": "application/json" }, body: JSON.stringify(payload) });
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
    const msgs = chunkEmbeds(buildEmbeds(scan, site, { onlyBets: !!opts.only_bets }));
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

async function notifyFailure(edit, err) {
  try {
    await edit({ content: "ORACLE FC scan error: " + clip(err && err.message, 300) });
  } catch (_) {
    // interaction already gone; nothing else to do
  }
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (request.method === "GET") {
      if (url.pathname === "/health") return json({ ok: true, today_et: todayET() });
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
