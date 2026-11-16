// Polymarket Gamma + CLOB -> the internal event shape bestbet.js prices. Mirror of
// oraclefc/market/polymarket_prices.py (kept in sync by tests/test_polymarket_prices.py).
// POST-HOC only: used by the Edge tab against forecasts that were frozen before the fetch.
(function (root) {
  const GAMMA = "https://gamma-api.polymarket.com", CLOB = "https://clob.polymarket.com";
  const SIBLINGS = ["-more-markets", "-exact-score"];
  const FULL_TIME = new Set(["moneyline", "both_teams_to_score", "totals", "soccer_team_totals", "spreads", "soccer_exact_score"]);
  const list = (v) => { if (typeof v === "string") { try { v = JSON.parse(v); } catch { return []; } } return Array.isArray(v) ? v : []; };
  const usd = (x) => Math.round((x || 0) * 1e6);
  const hcpLabel = (x) => (x > 0 ? "+" : "") + String(Number(x));

  function bookQuote(book) {
    const levels = (side) => ((book || {})[side] || []).map((x) => [Number(x.price), Number(x.size)]).filter(([p, n]) => p > 0 && p < 1 && n > 0);
    const asks = levels("asks"), bids = levels("bids");
    const ask = asks.length ? Math.min(...asks.map((x) => x[0])) : null, bid = bids.length ? Math.max(...bids.map((x) => x[0])) : null;
    return { ask, bid, ask_depth: ask == null ? 0 : asks.filter((x) => x[0] <= ask + 1e-9).reduce((s, x) => s + x[1], 0), timestamp: (book || {}).timestamp ?? null };
  }
  function fee(gm) {
    const s = gm.feeSchedule || {};
    if (gm.feesEnabled === false) return { rate: 0, exponent: 1, source: "market" };
    if (s.rate != null) return { rate: Number(s.rate), exponent: Number(s.exponent ?? 1), source: "market" };
    return { rate: 0.05, exponent: 1, source: "assumed" };
  }
  function adaptMarket(gm, home, away, books) {
    const t = gm.sportsMarketType;
    if (!FULL_TIME.has(t) || gm.closed || gm.active === false || gm.acceptingOrders === false) return [];
    const outcomes = list(gm.outcomes), tokens = list(gm.clobTokenIds).map(String);
    if (outcomes.length !== 2 || tokens.length !== 2) return [];
    const q = tokens.map((tok) => books[tok] || {}), volume = gm.volumeNum ?? null;
    const base = { sportsMarketType: t, status: "open", provider: "polymarket", rulesPrimary: gm.description || "", conditionId: gm.conditionId ?? null, slug: gm.slug ?? null, fee: fee(gm) };
    const group = String(gm.groupItemTitle || "").trim(), slug = String(gm.slug || ""), line = gm.line;
    if (outcomes[0] === "Yes" && outcomes[1] === "No") {
      let title;
      if (t === "moneyline") { title = slug.endsWith("-draw") || group.toLowerCase().startsWith("draw") ? "Draw" : group; if (!["Draw", home, away].includes(title)) return []; }
      else if (t === "both_teams_to_score") title = "Both Teams to Score";
      else if (t === "soccer_exact_score") title = group;
      else return [];
      return [{ ...base, marketId: `POLY-${gm.id}`, title, isTeamMarket: false, pricing: { buyYesPriceUsd: usd(q[0].ask), sellYesPriceUsd: usd(q[0].bid),
        buyNoPriceUsd: usd(q[1].ask), sellNoPriceUsd: usd(q[1].bid), volume, askDepthYes: q[0].ask_depth ?? null, askDepthNo: q[1].ask_depth ?? null } }];
    }
    const out = [];
    for (let i = 0; i < 2; i++) {
      const label = String(outcomes[i]);
      const m = { ...base, marketId: `POLY-${gm.id}-${i}`, title: label, isTeamMarket: true,
        pricing: { buyYesPriceUsd: usd(q[i].ask), sellYesPriceUsd: usd(q[i].bid), buyNoPriceUsd: 0, sellNoPriceUsd: 0, volume, askDepthYes: q[i].ask_depth ?? null } };
      if (t === "totals" || t === "soccer_team_totals") {
        if (outcomes[0] !== "Over" || outcomes[1] !== "Under" || line == null) return [];
        m.sportsLine = Number(line);
        if (t === "soccer_team_totals") { const side = slug.match(/-team-total-(home|away)-/); if (!side) return []; m.team = { name: side[1] === "home" ? home : away }; }
      } else if (t === "spreads") {
        if (line == null || !(outcomes.includes(home) && outcomes.includes(away)) || home === away) return [];
        const hcp = i === 0 ? Number(line) : -Number(line);
        m.team = { name: label }; m.sportsLine = Number(line); m.marketOptions = [{ label: `${label} ${hcpLabel(hcp)}` }];
      } else return [];
      out.push(m);
    }
    return out;
  }
  function adaptEvent(events, home, away, books) {
    const parent = events[0] || {};
    return { eventId: `POLY-${parent.id}`, isLive: Boolean(parent.live || parent.ended || parent.closed),
      markets: events.flatMap((ev) => (ev.markets || []).flatMap((gm) => adaptMarket(gm, home, away, books))) };
  }
  function tokenIds(events) {
    return events.flatMap((ev) => (ev.markets || []).filter((gm) => FULL_TIME.has(gm.sportsMarketType) && !gm.closed).flatMap((gm) => list(gm.clobTokenIds).map(String)));
  }
  async function getJSON(url, init) { const r = await fetch(url, { cache: "no-store", ...init }); if (!r.ok) throw new Error(`${r.status} ${url}`); return r.json(); }
  async function fetchBooks(tokens) {
    const out = {};
    for (let i = 0; i < tokens.length; i += 100) {
      const books = await getJSON(`${CLOB}/books`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(tokens.slice(i, i + 100).map((t) => ({ token_id: t }))) });
      for (const b of books || []) out[String(b.asset_id)] = bookQuote(b);
    }
    return out;
  }
  /** Live event (internal shape) for one frozen fixture; throws if the id no longer names that fixture. */
  async function fetchEvent(fixture) {
    const gid = String(fixture.event_id).replace(/^POLY-/, "");
    const parent = await getJSON(`${GAMMA}/events/${encodeURIComponent(gid)}`);
    if (String(parent.id) !== gid || (fixture.slug && parent.slug !== fixture.slug)) throw new Error("event identity mismatch");
    const events = [parent];
    for (const s of SIBLINGS) { const found = await getJSON(`${GAMMA}/events?slug=${encodeURIComponent(parent.slug + s)}`); events.push(...(Array.isArray(found) ? found : []).filter((e) => e.slug === parent.slug + s)); }
    return adaptEvent(events, fixture.home_name, fixture.away_name, await fetchBooks(tokenIds(events)));
  }
  /** Identity-only fixture list for a date (ET). Prices and volumes are deliberately not copied. */
  async function fixturesLive(date, dateOf) {
    const start = new Date(date + "T00:00:00Z").getTime() - 6 * 36e5, out = [];
    for (let off = 0; off < 3000; off += 100) {
      const page = await getJSON(`${GAMMA}/events?tag_id=100350&closed=false&limit=100&offset=${off}&order=id&ascending=true&start_time_min=${new Date(start).toISOString()}&start_time_max=${new Date(start + 36 * 36e5).toISOString()}`);
      for (const ev of page) {
        const m = String(ev.title || "").match(/^(.+?)\s+vs\.?\s+(.+)$/);
        if (!m || !ev.startTime || !/^[a-z0-9]+-[a-z0-9]+-[a-z0-9]+-\d{4}-\d{2}-\d{2}$/.test(ev.slug || "") || dateOf(ev.startTime) !== date) continue;
        out.push({ event_id: `POLY-${ev.id}`, home_name: m[1].trim(), away_name: m[2].trim(), competition: ev.sport?.name || ev.slug.split("-")[0], subcategory: ev.slug.split("-")[0], kickoff_utc: new Date(ev.startTime).toISOString(), slug: ev.slug });
      }
      if (page.length < 100) break;
    }
    return out;
  }
  const api = { GAMMA, CLOB, bookQuote, fee, adaptMarket, adaptEvent, tokenIds, fetchBooks, fetchEvent, fixturesLive };
  if (typeof module !== "undefined" && module.exports) module.exports = api; else root.Polymarket = api;
})(typeof window !== "undefined" ? window : globalThis);
