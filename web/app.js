// ORACLE FC dashboard. Forecast views never read market prices.
// The Edge tab fetches prices only to compare against already-frozen forecasts.
const JUP = "https://api.jup.ag/prediction/v1";
const $ = (s) => document.querySelector(s);
const pct = (x, d = 1) => (x == null ? "–" : (100 * x).toFixed(d) + "%");
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
let MODE = "static", CURRENT = null;
const CURRENT_DATE = () => (CURRENT && CURRENT.date) || null;

function todayET() {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" }).format(new Date());
}
function etTime(iso) {
  return new Date(iso).toLocaleString("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit", month: "short", day: "numeric" }) + " ET";
}
async function getJSON(url) {
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) throw new Error(`${r.status} ${url}`);
  return r.json();
}
async function detectMode() {
  try { const h = await getJSON("api/health"); if (h.mode === "api") MODE = "api"; } catch (_) {}
}

// ---------------------------------------------------------------- fixtures (live, prices stripped)
async function jupiterFixturesLive(date) {
  const now = Math.floor(Date.now() / 1000);
  let start = 0, out = [];
  for (let page = 0; page < 12; page++) {
    const u = `${JUP}/events?category=sports&tags=soccer&start=${start}&end=${start + 100}&sortBy=beginAt&sortDirection=asc`;
    const j = await getJSON(u);
    for (const ev of j.data || []) {
      const t = ev.metadata?.title || "";
      const m = t.match(/^(.+?)\s+vs\.?\s+(.+)$/);
      if (!m || !ev.beginAt) continue;
      const iso = new Date(Number(ev.beginAt) * 1000).toISOString();
      if (new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" }).format(new Date(iso)) !== date) continue;
      // allow-list: identity fields only; prices/volumes are deliberately not copied
      out.push({ event_id: ev.eventId, home_name: m[1], away_name: m[2], competition: ev.metadata?.league || ev.subcategory, subcategory: ev.subcategory, kickoff_utc: iso });
    }
    if (!j.pagination?.hasNext) break;
    start += 100;
    await new Promise((r) => setTimeout(r, 600));
  }
  return out;
}

// ---------------------------------------------------------------- forecasts
async function loadForecasts(date) {
  $("#status").textContent = MODE === "api" ? "Running ORACLE FC for every Jupiter game on " + date + "…" : "Loading frozen forecasts…";
  if (MODE === "api") return getJSON(`api/forecasts?date=${date}`);
  try { return await getJSON(`data/dates/${date}.json`); }
  catch (_) {
    const fx = await jupiterFixturesLive(date).catch(() => []);
    return { date, live_only: true, n_fixtures: fx.length, n_forecast: 0,
      forecasts: fx.map((f) => ({ status: "pending_pipeline", fixture: f, data_quality: ["Not yet simulated: the scheduled pipeline forecasts today → +7 days every 3 hours (or run the 'pipeline' workflow with this date)."] })) };
  }
}

function card(fc) {
  const f = fc.fixture, s = fc.simulation, el = document.createElement("article");
  el.className = "card";
  const head = `<div class="comp">${esc(f.competition)} · ${f.kickoff_utc ? etTime(f.kickoff_utc) : ""}</div>`;
  if (fc.status !== "ok") {
    el.innerHTML = `${head}<h3>${esc(f.home_name)} vs ${esc(f.away_name)}</h3><p class="warn">${fc.status === "pending_pipeline" ? "Awaiting simulation" : "No forecast"}</p><ul class="muted">${(fc.data_quality || []).map((d) => `<li>${esc(d)}</li>`).join("")}</ul>`;
    return el;
  }
  const ms = s.modal_score, b = s.total_buckets;
  const grid = s.score_grid.slice(0, 6).map((row, i) => `<tr><th>${i}</th>${row.slice(0, 6).map((p) => `<td style="background:rgba(214,156,8,${Math.min(0.9, p * 6)})">${(100 * p).toFixed(1)}</td>`).join("")}</tr>`).join("");
  el.dataset.eid = f.event_id || "";
  el.innerHTML = `${head}
    <div class="bb" data-bb>${bbBanner(window.BB && window.BB.date === CURRENT_DATE() ? window.BB.byId[f.event_id] : null)}</div>
    <div class="score"><div class="team">${esc(f.home_name)}</div><b>${ms.home}</b>–<b>${ms.away}</b><div class="team">${esc(f.away_name)}</div></div>
    <div class="modal-p">Most likely exact score · ${pct(ms.p)} · xG ${s.xg_home.toFixed(2)} – ${s.xg_away.toFixed(2)}</div>
    <div class="bar"><div class="h" style="width:${100 * s.p_home}%">${pct(s.p_home, 0)}</div><div class="d" style="width:${100 * s.p_draw}%">${pct(s.p_draw, 0)}</div><div class="a" style="width:${100 * s.p_away}%">${pct(s.p_away, 0)}</div></div>
    <div class="kv"><div><span>BTTS</span>${pct(s.btts)}</div><div><span>Over 2.5</span>${pct(s.totals_over["over_2.5"])}</div><div><span>Median total</span>${s.median_total}</div><div><span>Confidence</span>${esc(fc.confidence.tier)}</div></div>
    <div class="tops">${s.top_scores.map((t) => `<span>${t.home}-${t.away} · ${pct(t.p)}</span>`).join("")}</div>
    <div class="muted">Goals 0–1 ${pct(b["0-1"])} · 2 ${pct(b["2"])} · 3 ${pct(b["3"])} · 4 ${pct(b["4"])} · 5+ ${pct(b["5+"])}</div>
    ${ctxBlock(fc)}
    <details><summary>Score grid (home rows × away cols, %)</summary><table class="grid"><tr><th></th>${[0, 1, 2, 3, 4, 5].map((x) => `<th>${x}</th>`).join("")}</tr>${grid}</table></details>
    <details><summary>Full ORACLE FC report</summary><pre class="report">${esc(fc.report_text)}</pre></details>
    <div class="muted">Matched as ${esc(f.home_matched)} v ${esc(f.away_matched)} · frozen ${fc.frozen_at ? etTime(fc.frozen_at) : "(not frozen)"}</div>`;
  return el;
}

function render(res) {
  CURRENT = res;
  const ok = res.forecasts.filter((f) => f.status === "ok");
  const bad = res.forecasts.filter((f) => f.status !== "ok");
  $("#status").textContent = "";
  $("#summary").innerHTML = [
    `<span class="pill">${res.n_fixtures} Jupiter soccer games on ${esc(res.date)} (ET)</span>`,
    `<span class="pill">${ok.length} simulated</span>`,
    `<span class="pill">${bad.length} without forecast</span>`,
    res.model_version ? `<span class="pill">model ${esc(res.model_version)}</span>` : "",
    res.data_cutoff ? `<span class="pill">data cutoff ${esc(res.data_cutoff)}</span>` : "",
    res.live_only ? `<span class="pill warn">live fixture list · not yet simulated</span>` : "",
  ].join("");
  const cards = $("#cards"); cards.innerHTML = "";
  ok.forEach((f) => cards.appendChild(card(f)));
  bad.filter((f) => f.status === "pending_pipeline").forEach((f) => cards.appendChild(card(f)));
  const uns = bad.filter((f) => f.status !== "pending_pipeline");
  $("#unsupported").innerHTML = uns.length ? `<div class="unsup"><h3>Not forecast (${uns.length}) — honest gaps</h3><ul>${uns.map((f) => `<li><b>${esc(f.fixture.home_name)} vs ${esc(f.fixture.away_name)}</b> (${esc(f.fixture.competition)}): ${esc((f.data_quality || []).filter((d) => /UNMATCHED|UNSUPPORTED|Kick-off/.test(d)).join(" ") || f.status)}</li>`).join("")}</ul></div>` : "";
  renderBestBets();
  if (!res.forecasts.length) $("#status").textContent = "No Jupiter soccer games found for this date (Jupiter only lists active/upcoming events).";
}

// ---------------------------------------------------------------- post-hoc BEST BET (after freezing)
const cents = (x) => (x == null ? "–" : (100 * x).toFixed(1) + "¢");
const evp = (x) => (x >= 0 ? "+" : "") + (100 * x).toFixed(1) + "%";
function bbBanner(g) {
  if (!window.BB || window.BB.date !== CURRENT_DATE()) return `<div class="bb-wait muted">Best bet: waiting for post-hoc Jupiter prices…</div>`;
  if (!g) return `<div class="bb-no"><b>NO BET</b> <span class="muted">— no Jupiter prices captured for this game</span></div>`;
  if (g.verdict !== "BET") {
    const c = g.closest;
    return `<div class="bb-no"><b>NO BET</b> <span class="muted">— ${esc(g.reason || "no selection with model P > 50% and positive EV at the ask after fees")}${c ? ` · closest: ${esc(c.label)} (P ${pct(c.model_p)}, ask ${cents(c.ask)}, EV ${evp(c.ev_per_dollar)})` : ""}</span></div>`;
  }
  const b = g.bet;
  return `<div class="bb-yes"><div class="bb-tag">BEST BET</div><div class="bb-sel">${esc(b.label)} <span class="bb-side">${esc(b.side)}</span></div>
    <div class="bb-nums"><span><i>EV</i>${evp(b.ev_per_dollar)}</span><span><i>Model</i>${pct(b.model_p)}</span><span><i>Ask</i>${cents(b.ask)}</span><span><i>Edge</i>${b.edge_pp >= 0 ? "+" : ""}${b.edge_pp.toFixed(1)} pp</span></div>
    <div class="muted small">Cost ${cents(b.cost_per_contract)}/contract incl. ${cents(b.fee_per_contract)} fee · ${g.n_eligible} eligible of ${g.n_priced} priced sides${b.thin_book ? " · ⚠ thin book" : ""}${b.volume != null ? ` · vol ${Number(b.volume).toLocaleString()}` : ""}</div></div>`;
}
function setBestBets(date, games, fetchedAt, source) {
  window.BB = { date, games, fetchedAt, source, byId: Object.fromEntries(games.map((g) => [g.event_id, g])) };
  document.querySelectorAll("#cards .card").forEach((el) => { const s = el.querySelector("[data-bb]"); if (s) s.innerHTML = bbBanner(window.BB.byId[el.dataset.eid]); });
  renderBestBets();
}
function renderBestBets() {
  const box = $("#best-bets"); if (!box) return;
  const B = window.BB;
  if (!B || B.date !== CURRENT_DATE() || !B.games || !B.games.length) { if (!B || B.date !== CURRENT_DATE()) box.innerHTML = ""; return; }
  const n = B.games.length, nb = B.games.filter((g) => g.verdict === "BET").length;
  const rows = B.games.map((g) => {
    const b = g.bet;
    return `<tr class="${b ? "" : "muted"}"><td class="l">${g.kickoff_utc ? etTime(g.kickoff_utc) : ""}</td><td class="l">${esc(g.home)} v ${esc(g.away)}<div class="muted small">${esc(g.competition || "")}</div></td>
      ${b ? `<td class="l"><b>${esc(b.label)}</b> <span class="bb-side">${esc(b.side)}</span></td><td class="pos">${evp(b.ev_per_dollar)}</td><td>${pct(b.model_p)}</td><td>${cents(b.ask)}</td><td>${cents(b.cost_per_contract)}</td><td>${b.edge_pp >= 0 ? "+" : ""}${b.edge_pp.toFixed(1)}</td>`
          : `<td class="l"><b>NO BET</b> <span class="small">${esc(g.reason || "")}</span></td><td>–</td><td>–</td><td>–</td><td>–</td><td>–</td>`}</tr>`;
  }).join("");
  box.innerHTML = `<h2>Best Bets · ${esc(B.date)} <small class="muted">${nb} bet · ${n - nb} no bet</small></h2>
    <p class="posthoc small">⚠️ POST-HOC: prices ${esc(B.source)} ${B.fetchedAt ? etTime(B.fetchedAt) : ""}, after the forecasts were frozen; they never feed the model. Eligible = model P &gt; 50% and EV &gt; 0 buying at the Jupiter ask (YES or NO) incl. Jupiter 2% builder fee + Polymarket sports taker fee 0.05·p(1−p). EV per $1 = P / (ask + fee) − 1. Highest EV per game. Research comparison, not betting advice.</p>
    <details open><summary>Summary table (${n} games)</summary><table><tr><th class="l">Kick-off</th><th class="l">Match</th><th class="l">Best bet</th><th>EV</th><th>Model P</th><th>Ask</th><th>Cost incl. fee</th><th>Edge pp</th></tr>${rows}</table></details>`;
}

// ---------------------------------------------------------------- post-hoc edge
function mid(pr) {
  const ask = (pr?.buyYesPriceUsd || 0) / 1e6, bid = (pr?.sellYesPriceUsd || 0) / 1e6;
  return { ask: ask || null, bid: bid || null, mid: ask && bid && ask - bid <= 0.15 ? (ask + bid) / 2 : null };
}
function parseMarkets(ev, home, away) {
  const out = { moneyline: {}, btts: null, totals: {}, exact: {} };
  for (const m of ev.markets || []) {
    if (m.status && m.status !== "open") continue;
    const t = m.sportsMarketType, title = (m.title || "").trim(), p = mid(m.pricing);
    if (t === "moneyline" && !m.isTeamMarket) {
      if (title.toLowerCase() === "draw") out.moneyline.draw = p;
      else if (title === home) out.moneyline.home = p;
      else if (title === away) out.moneyline.away = p;
    } else if (t === "both_teams_to_score") out.btts = p;
    else if (t === "totals" && (title === "Over" || title === "Under") && m.sportsLine != null && p.mid != null) {
      const line = Number(m.sportsLine), po = title === "Over" ? p.mid : 1 - p.mid;
      if (title === "Over" || !(line in out.totals)) out.totals[line] = { p_over: po };
    } else if (t === "soccer_exact_score") {
      const em = title.match(/(\d+)\s*-\s*(\d+)/);
      if (em && title !== "Any Other Score") out.exact[`${em[1]}-${em[2]}`] = p;
    }
  }
  return out;
}
function edges(fc, mk) {
  const s = fc.simulation, f = fc.fixture, rows = [];
  const push = (market, sel, model, m) => { if (m && m.mid != null) rows.push({ market, sel, model, mkt: m.mid, ask: m.ask, edge: model - m.mid }); };
  push("1X2", f.home_name, s.p_home, mk.moneyline.home);
  push("1X2", "Draw", s.p_draw, mk.moneyline.draw);
  push("1X2", f.away_name, s.p_away, mk.moneyline.away);
  push("BTTS", "Yes", s.btts, mk.btts);
  for (const [line, v] of Object.entries(mk.totals)) {
    const k = `over_${Number(line)}`;
    if (k in s.totals_over) rows.push({ market: "Total", sel: `Over ${line}`, model: s.totals_over[k], mkt: v.p_over, ask: null, edge: s.totals_over[k] - v.p_over });
  }
  for (const [sc, p] of Object.entries(mk.exact)) {
    const [h, a] = sc.split("-").map(Number);
    if (h < s.score_grid.length && a < s.score_grid.length) push("Exact", sc, s.score_grid[h][a], p);
  }
  return rows;
}
function renderEdge(events, meta) {
  const min = Number($("#min-edge").value) || 0, only = $("#only-1x2").checked;
  $("#edge-meta").innerHTML = meta;
  const rows = [];
  const pre = $("#pre-only").checked;
  for (const e of events) for (const r of e.rows) {
    if (pre && e.market_after_kickoff) continue;
    if (only && r.market === "Exact") continue;
    if (Math.abs(r.edge) < min) continue;
    rows.push({ ...r, e });
  }
  rows.sort((a, b) => b.edge - a.edge);
  $("#edge-table").innerHTML = rows.length ? `<table><tr><th class="l">Match</th><th class="l">Market</th><th class="l">Selection</th><th>Model</th><th>Market mid</th><th>Ask</th><th>Edge (model − mid)</th><th class="l">Forecast frozen</th></tr>${rows.map((r) => `<tr><td class="l">${esc(r.e.home)} v ${esc(r.e.away)}<div class="muted">${esc(r.e.competition)}</div></td><td class="l">${r.market}</td><td class="l">${esc(r.sel)}</td><td>${pct(r.model)}</td><td>${pct(r.mkt)}</td><td>${r.ask ? pct(r.ask) : "–"}</td><td class="${r.edge > 0 ? "pos" : "neg"}">${(100 * r.edge).toFixed(1)} pp</td><td class="l muted">${etTime(r.e.frozen_at)}</td></tr>`).join("")}</table>` : `<p class="muted">No comparisons above the threshold.</p>`;
}
async function liveEdge() {
  if (!CURRENT) return;
  const fcs = CURRENT.forecasts.filter((f) => f.status === "ok" && f.frozen_at && f.fixture.event_id);
  const fetchedAt = new Date().toISOString(), events = [], games = [];
  $("#edge-meta").textContent = `Fetching live prices for ${fcs.length} frozen forecasts…`;
  for (const fc of fcs) {
    if (fc.frozen_at > fetchedAt) continue; // only forecasts frozen before the price snapshot
    try {
      const ev = await getJSON(`${JUP}/events/${encodeURIComponent(fc.fixture.event_id)}?includeMarkets=true&includeAllMarkets=true`);
      const mk = parseMarkets(ev.data || ev, fc.fixture.home_name, fc.fixture.away_name);
      events.push({ home: fc.fixture.home_name, away: fc.fixture.away_name, competition: fc.fixture.competition, frozen_at: fc.frozen_at, market_after_kickoff: fetchedAt >= fc.fixture.kickoff_utc, rows: edges(fc, mk) });
      const g = { event_id: fc.fixture.event_id, home: fc.fixture.home_name, away: fc.fixture.away_name, competition: fc.fixture.competition, kickoff_utc: fc.fixture.kickoff_utc };
      if (fetchedAt >= fc.fixture.kickoff_utc) Object.assign(g, { verdict: "NO BET", reason: "prices fetched after kick-off (in-play), not pre-match" });
      else Object.assign(g, BestBet.bestBet(BestBet.selectionsFromEvent(ev.data || ev, fc.fixture.home_name, fc.fixture.away_name), fc.simulation.score_grid, fc.simulation));
      games.push(g);
    } catch (e) { console.warn(e); }
    await new Promise((r) => setTimeout(r, 350));
  }
  games.sort((a, b) => (a.kickoff_utc || "").localeCompare(b.kickoff_utc || ""));
  setBestBets(CURRENT.date, games, fetchedAt, "fetched live in your browser at");
  window.EDGE = { events, meta: `Live Jupiter prices fetched ${etTime(fetchedAt)} for ${events.length} events · compared against forecasts frozen earlier.` };
  renderEdge(EDGE.events, EDGE.meta);
}
async function loadEdge(date) {
  try {
    const j = MODE === "api" ? await getJSON(`api/edge?date=${date}`) : await getJSON(`data/edge/${date}.json`);
    const events = j.events.map((e) => ({ ...e, rows: e.rows.map((r) => ({ market: r.market === "Exact score" ? "Exact" : r.market, sel: r.selection, model: r.model_p, mkt: r.market_mid, ask: r.market_ask, edge: r.edge_vs_mid })) }));
    if (j.best_bets && j.best_bets.games) setBestBets(date, j.best_bets.games, j.market_fetched_at, "snapshot by the pipeline at");
    else setBestBets(date, [], null, "not captured");
    window.EDGE = { events, meta: `Pipeline price snapshot ${j.market_fetched_at ? etTime(j.market_fetched_at) : ""} · ${events.length} events.` };
    renderEdge(EDGE.events, EDGE.meta);
  } catch (_) {
    setBestBets(date, [], null, "not captured");
    $("#best-bets").innerHTML = `<p class="muted">Best bets: no stored post-hoc price snapshot for this date yet — use “Fetch live Jupiter prices now” on the Edge tab.</p>`;
    $("#edge-meta").textContent = "No stored post-hoc snapshot for this date yet. Use “Fetch live Jupiter prices now”.";
    $("#edge-table").innerHTML = "";
  }
}

// ---------------------------------------------------------------- model tab
function ctxBlock(fc) {
  const c = fc.context; if (!c) return "";
  const f = fc.fixture, nm = { home: f.home_matched || f.home_name, away: f.away_matched || f.away_name };
  const badge = (st) => `<span class="lu lu-${esc(st || "none")}">${esc((st || "none").toUpperCase())}</span>`;
  const lu = ["home", "away"].map((sd) => { const x = (c.lineups || {})[sd] || {};
    return `<div><b>${esc(nm[sd])}</b> ${badge(x.status)} ${x.formation ? esc(x.formation) : ""}<div class="muted small">${(x.starters || []).map((p) => esc(p.name)).join(", ") || "—"}</div></div>`; }).join("");
  const ab = ["home", "away"].flatMap((sd) => ((c.absences || {})[sd] || []).map((a) => `<li><b>${esc(nm[sd])}</b>: ${esc(a.player)} — ${esc(a.type || "")}${a.chance_of_playing != null ? ` (${a.chance_of_playing}%)` : ""}, ${esc(a.expected_return || "")} <span class="muted">[${esc(a.source)}, ${a.fetched_at ? etTime(a.fetched_at) : "?"}]</span></li>`));
  const w = c.weather;
  const wx = w ? `${w.temp_c.toFixed(1)} °C · wind ${w.wind_ms.toFixed(1)} m/s · rain ${w.precip_mm_2h.toFixed(1)} mm` : "no forecast yet";
  const sh = (c.factor_shifts || []).filter((x) => x.d_p_home_pp != null).map((x) => `<tr class="${x.applied ? "" : "muted"}"><td class="l">${esc(x.factor)}${x.applied ? "" : " <small>(not applied)</small>"}</td><td>${x.d_p_home_pp.toFixed(2)}</td><td>${x.d_p_draw_pp.toFixed(2)}</td><td>${x.d_p_away_pp.toFixed(2)}</td></tr>`).join("");
  const t = c.total_shift;
  return `<details class="ctx"><summary>Match context · lineups ${badge(((c.lineups || {}).home || {}).status)} / ${badge(((c.lineups || {}).away || {}).status)} · ${ab.length} absences</summary>
    <div class="lineups">${lu}</div>
    <div class="muted small">Weather: ${wx} · Rest ${c.rest?.home?.rest_days ?? "?"}d / ${c.rest?.away?.rest_days ?? "?"}d · away travel ${c.travel?.away_travel_km ?? "?"} km</div>
    <ul class="small">${ab.join("") || "<li>No absences listed</li>"}</ul>
    ${sh ? `<table class="shift"><tr><th class="l">Factor (pp)</th><th>Home</th><th>Draw</th><th>Away</th></tr>${sh}${t && (c.factor_shifts || []).some((x) => x.applied && !x.factor.startsWith("Understat")) ? `<tr><td class="l"><b>All context</b></td><td>${t.d_p_home_pp.toFixed(2)}</td><td>${t.d_p_draw_pp.toFixed(2)}</td><td>${t.d_p_away_pp.toFixed(2)}</td></tr>` : ""}</table>` : `<p class="muted small">No context family passed validation — shown for information only.</p>`}
  </details>`;
}

async function loadModel() {
  try {
    const j = MODE === "api" ? await getJSON("api/model") : await getJSON("data/model.json");
    const bt = j.backtest, reg = j.registry || {};
    if (!bt) { $("#model").innerHTML = "<p>No backtest yet.</p>"; return; }
    const rows = Object.entries(bt.models).sort((a, b) => a[1].rps - b[1].rps);
    $("#model").innerHTML = `<h2>Champion: ${esc(reg.champion?.name)} <small class="muted">${esc(reg.champion?.version)}</small></h2>
      <p class="muted">Walk-forward out-of-sample test ${esc(bt.test_window?.join(" → "))}, n = ${bt.n_matches?.toLocaleString()} matches. Lower is better for log loss / RPS / Brier / MAE.</p>
      <table><tr><th class="l">Model</th><th>Log loss</th><th>RPS</th><th>Brier</th><th>Exact log score</th><th>Top-1</th><th>Top-3</th><th>Top-5</th><th>MAE goals</th></tr>
      ${rows.map(([k, m]) => `<tr><td class="l">${esc(k)}</td><td>${m.log_loss.toFixed(4)}</td><td>${m.rps.toFixed(4)}</td><td>${m.brier.toFixed(4)}</td><td>${m.exact_log_score.toFixed(4)}</td><td>${pct(m.top1)}</td><td>${pct(m.top3)}</td><td>${pct(m.top5)}</td><td>${m.mae_goals.toFixed(3)}</td></tr>`).join("")}</table>
      <p>Ensemble weights: ${esc(JSON.stringify(reg.champion?.ensemble_weights))}</p>
      <p class="muted">${esc(bt.promotion_rule)}</p>${ctxModel(j.context)}<p><a href="https://github.com/lucksociety/oracle-fc/blob/main/docs/BACKTEST.md" target="_blank">Full backtest report →</a></p>`;
  } catch (e) { $("#model").innerHTML = `<p class="muted">Model info unavailable (${esc(e.message)})</p>`; }
}

function ctxModel(cx) {
  if (!cx || !cx.families) return "";
  const r = Object.entries(cx.families).map(([k, v]) => `<tr><td class="l">${esc(k)}</td><td>${v.n.toLocaleString()}</td><td>${v.delta.rps.mean_diff.toFixed(5)} [${v.delta.rps.ci95.map((x) => x.toFixed(5)).join(", ")}]</td><td>${v.delta.log_loss.mean_diff.toFixed(5)} [${v.delta.log_loss.ci95.map((x) => x.toFixed(5)).join(", ")}]</td><td>${v.kept ? "<b>kept</b>" : "rejected"}</td></tr>`).join("");
  return `<h2>Context features (lineups, players, rest, travel, weather, xG)</h2><p class="muted">Champion/challenger, challenger − base (negative = better), test ${esc(cx.test_window?.join(" → "))}.</p>
    <table><tr><th class="l">Feature</th><th>n</th><th>ΔRPS [95% CI]</th><th>Δlog loss [95% CI]</th><th>Decision</th></tr>${r}</table>
    <p><a href="https://github.com/lucksociety/oracle-fc/blob/main/docs/CONTEXT_BACKTEST.md" target="_blank">Context backtest report →</a></p>`;
}

// ---------------------------------------------------------------- wiring
async function run() {
  const d = $("#date").value;
  history.replaceState(null, "", `?date=${d}`);
  try { render(await loadForecasts(d)); } catch (e) { $("#status").textContent = "Error: " + e.message; }
  loadEdge(d);
}
document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => {
  document.querySelectorAll(".tabs button").forEach((x) => x.classList.toggle("active", x === b));
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.id === "tab-" + b.dataset.tab));
}));
$("#go").addEventListener("click", run);
$("#live-edge").addEventListener("click", liveEdge);
$("#min-edge").addEventListener("input", () => window.EDGE && renderEdge(EDGE.events, EDGE.meta));
$("#pre-only").addEventListener("change", () => window.EDGE && renderEdge(EDGE.events, EDGE.meta));
$("#only-1x2").addEventListener("change", () => window.EDGE && renderEdge(EDGE.events, EDGE.meta));
(async () => {
  await detectMode();
  $("#date").value = new URLSearchParams(location.search).get("date") || todayET();
  loadModel();
  run();
})();
