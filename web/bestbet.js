// POST-HOC best bet per game — mirror of oraclefc/market/best_bet.py (kept in sync by tests/test_best_bet.py).
// Runs only on forecasts that were frozen BEFORE the prices were fetched; nothing flows back into the model.
(function (root) {
  const FEES = { polymarket: { builder_rate: 0.02, taker_rate: 0.05, exponent: 1.0 } };
  const MIN_P = 0.5, MIN_EV = 0.0;
  const EXACT_RE = /^(.+?)\s+(\d+)\s*-\s*(\d+)\s+(.+)$/, HCP_RE = /([+-]\d+(?:\.\d+)?)\s*$/;
  const fmtLine = (x) => String(Number(x));
  const fmtHcp = (x) => (x > 0 ? "+" : "") + String(Number(x));

  function feePerContract(price, provider) {
    const f = FEES[(provider || "").toLowerCase()] || FEES.polymarket;
    return f.builder_rate * price + f.taker_rate * Math.pow(price * (1 - price), f.exponent);
  }
  function negLabel(spec, label, home, away) {
    if (spec.kind === "1x2") return { H: `${away} or draw (NO on ${home})`, A: `${home} or draw (NO on ${away})`, D: "Either team to win (NO on draw)" }[spec.res];
    if (spec.kind === "btts") return "Both teams to score — NO";
    if (spec.kind === "exact") return `Any score except ${spec.h}-${spec.a}`;
    return `NO — ${label}`;
  }
  function selectionsFromEvent(ev, home, away) {
    const out = [], sideOf = { [home]: "home", [away]: "away" };
    for (const m of ev.markets || []) {
      if (m.status != null && m.status !== "open") continue;
      const t = m.sportsMarketType, title = (m.title || "").trim(), pr = m.pricing || {};
      const provider = (m.provider || "").toLowerCase() || null;
      const team = m.team && typeof m.team === "object" ? m.team.name : null;
      let spec = null, label = null;
      if (t === "moneyline" && !m.isTeamMarket) {
        const res = title.toLowerCase() === "draw" ? "D" : { home: "H", away: "A" }[sideOf[title]];
        if (res) { spec = { kind: "1x2", res }; label = res === "D" ? "Draw" : `${title} to win`; }
      } else if (t === "both_teams_to_score") { spec = { kind: "btts" }; label = "Both teams to score"; }
      else if ((t === "totals" || t === "soccer_team_totals") && (title === "Over" || title === "Under") && m.sportsLine != null) {
        const line = Number(m.sportsLine);
        if (Math.abs((line % 1) - 0.5) > 1e-9) continue;
        if (t === "totals") { spec = { kind: "total", line, over: title === "Over" }; label = `${title} ${fmtLine(line)} goals`; }
        else if (team in sideOf) { spec = { kind: "team_total", team: sideOf[team], line, over: title === "Over" }; label = `${team} ${title.toLowerCase()} ${fmtLine(line)} goals`; }
      } else if (t === "spreads" && team in sideOf) {
        const h = ((m.marketOptions || [{}])[0].label || "").match(HCP_RE);
        if (h && Math.abs((Math.abs(Number(h[1])) % 1) - 0.5) < 1e-9) { const hcp = Number(h[1]); spec = { kind: "spread", team: sideOf[team], hcp }; label = `${team} ${fmtHcp(hcp)}`; }
      } else if (t === "soccer_exact_score") {
        const em = title.match(EXACT_RE);
        if (em && em[1] in sideOf && em[4] in sideOf && em[1] !== em[4]) {
          const g = { [sideOf[em[1]]]: Number(em[2]), [sideOf[em[4]]]: Number(em[3])};
          spec = { kind: "exact", h: g.home, a: g.away }; label = `Exact score ${g.home}-${g.away}`;
        }
      }
      if (!spec) continue;
      const u = (x) => (x || 0) / 1e6;
      const ay = u(pr.buyYesPriceUsd), by = u(pr.sellYesPriceUsd), an = u(pr.buyNoPriceUsd), bn = u(pr.sellNoPriceUsd);
      const base = { market_id: m.marketId, market_type: t, volume: pr.volume, provider };
      if (ay > 0 && ay < 1) out.push({ ...base, label, side: "YES", outcome: spec, ask: ay, bid: by || null });
      if (an > 0 && an < 1) out.push({ ...base, label: negLabel(spec, label, home, away), side: "NO", outcome: { ...spec, neg: true }, ask: an, bid: bn || null });
    }
    return out;
  }
  function fromSim(spec, sim) {
    if (!sim) return null;
    if (spec.kind === "1x2") return sim[{ H: "p_home", D: "p_draw", A: "p_away" }[spec.res]] ?? null;
    if (spec.kind === "btts") return sim.btts ?? null;
    if (spec.kind === "total") { const o = (sim.totals_over || {})[`over_${fmtLine(spec.line)}`]; return o == null ? null : spec.over ? o : 1 - o; }
    return null;
  }
  function modelProb(spec, grid, sim) {
    let p = fromSim(spec, sim);
    if (p == null) {
      let tot = 0, hit = 0;
      grid.forEach((row, H) => row.forEach((q, A) => {
        tot += q;
        let ok;
        switch (spec.kind) {
          case "1x2": ok = { H: H > A, D: H === A, A: H < A }[spec.res]; break;
          case "btts": ok = H > 0 && A > 0; break;
          case "total": ok = spec.over ? H + A > spec.line : H + A < spec.line; break;
          case "team_total": { const G = spec.team === "home" ? H : A; ok = spec.over ? G > spec.line : G < spec.line; break; }
          case "spread": ok = (spec.team === "home" ? H - A : A - H) + spec.hcp > 0; break;
          case "exact": ok = H === spec.h && A === spec.a; break;
        }
        if (ok) hit += q;
      }));
      p = hit / tot;
    }
    return spec.neg ? 1 - p : p;
  }
  function evaluate(sels, grid, sim) {
    return sels.map((s) => {
      const p = modelProb(s.outcome, grid, sim), fee = feePerContract(s.ask, s.provider), ev = p / (s.ask + fee) - 1;
      return { ...s, model_p: p, fee_per_contract: fee, cost_per_contract: s.ask + fee, ev_per_dollar: ev, edge_pp: 100 * (p - s.ask),
        thin_book: !s.bid || s.ask - (s.bid || 0) > 0.1, fee_assumed: !((s.provider || "") in FEES), eligible: p > MIN_P && ev > MIN_EV };
    });
  }
  function bestBet(sels, grid, sim) {
    const rows = evaluate(sels, grid, sim);
    const elig = rows.filter((r) => r.eligible).sort((a, b) => b.ev_per_dollar - a.ev_per_dollar || b.model_p - a.model_p);
    const out = { n_priced: rows.length, n_eligible: elig.length };
    if (!elig.length) {
      out.verdict = "NO BET";
      const c = rows.filter((r) => r.model_p > MIN_P).sort((a, b) => b.ev_per_dollar - a.ev_per_dollar)[0];
      if (c) out.closest = c;
      return out;
    }
    out.verdict = "BET"; out.bet = elig[0]; out.alternatives = elig.slice(1, 3);
    return out;
  }
  const api = { FEES, MIN_P, feePerContract, selectionsFromEvent, modelProb, evaluate, bestBet };
  if (typeof module !== "undefined" && module.exports) module.exports = api; else root.BestBet = api;
})(typeof window !== "undefined" ? window : globalThis);
