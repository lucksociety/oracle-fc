// ORACLE FC simulator. Reads only the frozen forecast: 100,000 final scores are drawn from the
// forecast's score grid (the lineup-adjusted grid when "Use lineups" is on and one exists).
// The tested forecast, which bets are priced from, is never changed here.
(function () {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const pct = (x) => (x * 100).toFixed(1) + "%";
  const N_SIMS = 100000;

  // ---------------------------------------------------------------- engine
  function gridCdf(g) { const n = g.length, c = new Float64Array(n * n); let s = 0; for (let x = 0; x < n; x++) for (let y = 0; y < n; y++) { s += g[x][y]; c[x * n + y] = s; } for (let k = 0; k < c.length; k++) c[k] /= s; return c; }
  function sampleGrid(c) { const r = Math.random(); let lo = 0, hi = c.length - 1; while (lo < hi) { const m = (lo + hi) >> 1; if (c[m] < r) lo = m + 1; else hi = m; } return lo; }
  function summarise(c, n, G) {
    let h = 0, d = 0, a = 0, o15 = 0, o25 = 0, o35 = 0, btts = 0, sgh = 0, sga = 0; const cells = [];
    for (let x = 0; x < G; x++) for (let y = 0; y < G; y++) { const p = c[x * G + y] / n; if (!p) continue;
      if (x > y) h += p; else if (x === y) d += p; else a += p;
      if (x + y > 1) o15 += p; if (x + y > 2) o25 += p; if (x + y > 3) o35 += p; if (x && y) btts += p;
      sgh += x * p; sga += y * p; cells.push([x, y, p]); }
    cells.sort((p, q) => q[2] - p[2]);
    return { h, d, a, o15, o25, o35, btts, sgh, sga, top: cells.slice(0, 6) };
  }

  // ---------------------------------------------------------------- state
  let FCS = [], CUR = null, MARKET = {}, MK = { h: "", d: "", a: "" }, RES = null, running = false, RUNS = 0;
  const useLu = () => $("sim-lineups").checked;
  function active() {
    if (!CUR) return null;
    const s = CUR.simulation, ls = CUR.lineup_simulation || {}, on = useLu() && ls.applied && ls.score_grid;
    return { grid: (on ? ls : s).score_grid, lineups: !!on, key: (CUR.fixture.event_id || CUR.fixture.home_name) + "|" + (on ? "L" : "T") + "|" + (CUR.frozen_at || "") };
  }
  const names = () => [CUR.fixture.home_name, CUR.fixture.away_name];
  const lineup = (f, sd) => (((f.context || {}).lineups || {})[sd] || {});
  const hasXi = (f) => ["home", "away"].every((sd) => (lineup(f, sd).starters || []).length === 11);

  // ---------------------------------------------------------------- 100,000 runs
  // 100,000 draws take a few hundredths of a second, so they are paced over about half a second
  // with a live count: otherwise a click changes the numbers by tenths and looks like nothing ran.
  function runSims() {
    const a = active(); if (!a || running) return; running = true;
    const Gn = a.grid.length, counts = new Int32Array(Gn * Gn), cdf = gridCdf(a.grid), CH = 2500; let done = 0;
    const btn = $("sim-run"); btn.disabled = true; btn.textContent = "Running…"; $("sim-prog").style.width = "0";
    (function step() {
      for (let j = 0; j < CH; j++) counts[sampleGrid(cdf)]++;
      done += CH; $("sim-prog").style.width = done / N_SIMS * 100 + "%";
      const s = summarise(counts, done, Gn);
      $("sim-info").textContent = done.toLocaleString() + " of " + N_SIMS.toLocaleString();
      $("sim-bar").innerHTML = `<div class="h" style="width:${s.h * 100}%">${pct(s.h)}</div><div class="d" style="width:${s.d * 100}%">${pct(s.d)}</div><div class="a" style="width:${s.a * 100}%">${pct(s.a)}</div>`;
      if (done < N_SIMS) { requestAnimationFrame(step); return; }
      running = false; btn.disabled = false; btn.textContent = "Run 100,000 again";
      const now = active(); if (!now || now.key !== a.key) { runSims(); return; }
      RES = { s, counts, G: Gn, key: a.key }; RUNS++;
      $("sim-info").textContent = "Run " + RUNS + " finished " + new Date().toLocaleTimeString() + " · " + N_SIMS.toLocaleString() + " matches" + (a.lineups ? " · line-ups applied" : " · tested forecast");
      renderResults();
    })();
  }
  function renderResults() {
    if (!RES || !CUR) return; const { s, counts, G: Gn } = RES, [hn, an] = names(), t = CUR.simulation;
    $("sim-bar").innerHTML = `<div class="h" style="width:${s.h * 100}%">${pct(s.h)}</div><div class="d" style="width:${s.d * 100}%">${pct(s.d)}</div><div class="a" style="width:${s.a * 100}%">${pct(s.a)}</div>`;
    const rows = [["h", hn + " win", s.h, t.p_home], ["d", "Draw", s.d, t.p_draw], ["a", an + " win", s.a, t.p_away]];
    $("sim-odds").innerHTML = rows.map(([k, n, p, tp]) => `<tr><td class="l">${esc(n)}</td><td>${pct(p)}</td><td>${pct(tp)}</td><td><input id="sim-mkt-${k}" type="number" min="1" max="99" step="0.5" value="${esc(MK[k])}" aria-label="Market price for ${esc(n)} in cents"></td><td id="sim-gap-${k}">–</td></tr>`).join("");
    rows.forEach(([k, , p]) => { const f = () => { MK[k] = $("sim-mkt-" + k).value; const v = parseFloat(MK[k]), el = $("sim-gap-" + k);
        if (!(v > 0)) { el.textContent = "–"; el.className = ""; return; } const g = p * 100 - v; el.textContent = (g >= 0 ? "+" : "") + g.toFixed(1) + " pts"; el.className = g > 0 ? "pos" : "muted"; };
      $("sim-mkt-" + k).addEventListener("input", f); f(); });
    $("sim-kv").innerHTML = [[s.sgh.toFixed(2) + " – " + s.sga.toFixed(2), "Average score"], [pct(s.o15), "Over 1.5"], [pct(s.o25), "Over 2.5"], [pct(s.o35), "Over 3.5"], [pct(s.btts), "Both score"], ["±0.3 pts", "Sampling error"]]
      .map(([b, l]) => `<div><b>${b}</b><span>${l}</span></div>`).join("");
    const cell = (x, y) => { let c = 0; for (let i = x; i < (x === 5 ? Gn : x + 1); i++) for (let j = y; j < (y === 5 ? Gn : y + 1); j++) c += counts[i * Gn + j]; return c / N_SIMS; };
    let mx = 0; for (let x = 0; x < 6; x++) for (let y = 0; y < 6; y++) mx = Math.max(mx, cell(x, y));
    let h = '<div class="hd"></div>' + [0, 1, 2, 3, 4, "5+"].map((v) => `<div class="hd">${v}</div>`).join("");
    for (let x = 0; x < 6; x++) { h += `<div class="hd">${x === 5 ? "5+" : x}</div>`;
      for (let y = 0; y < 6; y++) { const p = cell(x, y); h += `<div class="c" style="background:rgba(214,156,8,${(p / mx * 0.75).toFixed(3)})">${(p * 100).toFixed(1)}</div>`; } }
    $("sim-heat").innerHTML = h;
    $("sim-heat-note").textContent = "Rows are " + hn + " goals, columns are " + an + " goals, values in percent.";
    $("sim-top").innerHTML = s.top.map(([x, y, p]) => `<tr><td class="l">${esc(hn)} ${x} – ${y} ${esc(an)}</td><td>${pct(p)}</td></tr>`).join("");
  }

  // ---------------------------------------------------------------- match picker and line-up note
  const BADGE = { confirmed: "confirmed", projected: "projected (not confirmed yet)", inferred: "estimated from recent minutes", none: "not published yet" };
  function note() {
    if (!CUR) { $("sim-lineup-note").textContent = ""; $("sim-xi").innerHTML = ""; return; }
    const ls = CUR.lineup_simulation, [hn, an] = names();
    const side = (sd, nm) => { const L = lineup(CUR, sd); return `${esc(nm)}: ${BADGE[L.status || "none"] || esc(L.status)}${L.formation ? ", " + esc(L.formation) : ""}`; };
    let eff;
    if (!ls) eff = `<b class="off">Not in this forecast.</b> It was frozen before line-ups were added to the simulator. Using the tested forecast.`;
    else if (!ls.applied) eff = `<b class="off">Probabilities unchanged.</b> ${esc(ls.reason)}`;
    else if (!useLu()) eff = `<b class="off">Switched off.</b> Using the tested forecast.`;
    else { const m = (v) => (v == null ? "" : "×" + Number(v).toFixed(3)); eff = `<b class="on">Applied.</b> ${esc(hn)} goals ${m(ls.home_rate_mult)}, ${esc(an)} goals ${m(ls.away_rate_mult)}. ${esc(ls.note || "")}`; }
    const wait = !CUR.context ? " This league has no line-up source." : hasXi(CUR) ? "" : " The source has not published an eleven for this match yet; it is re-checked every 20 minutes close to kick-off.";
    $("sim-lineup-note").innerHTML = `<b>Line-ups.</b> ${side("home", hn)} · ${side("away", an)}.${wait}<br>${eff}`;
    $("sim-xi").innerHTML = ["home", "away"].map((sd, i) => { const L = lineup(CUR, sd), st = L.starters || [];
      return `<div><b>${esc(names()[i])}</b> ${L.formation ? esc(L.formation) : ""}<div class="muted small">${st.length ? st.map((p) => esc((p.shirt != null ? p.shirt + " " : "") + p.name)).join(", ") : "No starting eleven available."}</div>${L.source ? `<div class="muted small">${esc(L.source)}</div>` : ""}</div>`; }).join("");
  }
  function marketFor(fc) {
    const e = MARKET[fc.fixture.event_id]; if (!e) return { h: "", d: "", a: "" }; const o = { h: "", d: "", a: "" };
    for (const r of e.rows || []) { if (r.market !== "1X2" || r.market_mid == null) continue; const k = r.selection === e.home ? "h" : r.selection === e.away ? "a" : /draw/i.test(r.selection) ? "d" : null; if (k) o[k] = (r.market_mid * 100).toFixed(1); }
    return o;
  }
  function pick(id) {
    CUR = FCS.find((f) => String(f.fixture.event_id) === String(id)) || null; RES = null;
    if (CUR) MK = marketFor(CUR);
    note();
    if (CUR) runSims(); else { $("sim-info").textContent = ""; ["sim-bar", "sim-odds", "sim-kv", "sim-heat", "sim-top"].forEach((i) => ($(i).innerHTML = "")); $("sim-heat-note").textContent = ""; }
  }
  const tm = (iso) => (iso ? new Date(iso).toLocaleString("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit" }) : "");
  window.Sim = {
    setForecasts(res) {
      FCS = (res.forecasts || []).filter((f) => f.status === "ok" && f.simulation && f.simulation.score_grid);
      const sel = $("sim-match"), keep = CUR && CUR.fixture.event_id;
      sel.innerHTML = FCS.length ? FCS.map((f) => `<option value="${esc(f.fixture.event_id)}">${esc(tm(f.fixture.kickoff_utc) + " · " + f.fixture.home_name + " v " + f.fixture.away_name + " (" + f.fixture.competition + ")" + (hasXi(f) ? "" : " · no line-ups yet"))}</option>`).join("") : '<option value="">No simulated matches on this date</option>';
      const now = Date.now(), withLu = (f) => f.lineup_simulation && f.lineup_simulation.applied, up = (f) => Date.parse(f.fixture.kickoff_utc) > now;
      const first = FCS.find((f) => String(f.fixture.event_id) === String(keep)) || FCS.find((f) => withLu(f) && up(f)) || FCS.find((f) => hasXi(f) && up(f)) || FCS.find(up) || FCS.find(hasXi) || FCS[0];
      if (first) sel.value = first.fixture.event_id; pick(sel.value);
    },
    setMarket(events) { MARKET = Object.fromEntries((events || []).map((e) => [e.event_id, e])); if (CUR && !MK.h && !MK.d && !MK.a) { MK = marketFor(CUR); renderResults(); } },
    open(id) { const sel = $("sim-match"); if ([...sel.options].some((o) => o.value === String(id))) { sel.value = id; pick(id); } },
  };
  $("sim-match").addEventListener("change", () => pick($("sim-match").value));
  $("sim-lineups").addEventListener("change", () => { note(); runSims(); });
  $("sim-run").addEventListener("click", runSims);
})();
