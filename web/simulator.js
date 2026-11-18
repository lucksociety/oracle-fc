// ORACLE FC match simulator. Reads only the frozen forecast: the final score of every simulated
// match is drawn from the forecast's score grid (the lineup-adjusted grid when "Use lineups" is on
// and one exists), then a match is written to fit that score with the real starting XIs in formation.
// The tested forecast, which bets are priced from, is never changed here.
(function () {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const pct = (x) => (x * 100).toFixed(1) + "%";
  const clampN = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
  const H1 = 47, NSLOT = 97, RED = 0.0008, XGM = 0.1244, N_SIMS = 100000;

  // ---------------------------------------------------------------- engine
  function gridCdf(g) { const n = g.length, c = new Float64Array(n * n); let s = 0; for (let x = 0; x < n; x++) for (let y = 0; y < n; y++) { s += g[x][y]; c[x * n + y] = s; } for (let k = 0; k < c.length; k++) c[k] /= s; return c; }
  function sampleGrid(c) { const r = Math.random(); let lo = 0, hi = c.length - 1; while (lo < hi) { const m = (lo + hi) >> 1; if (c[m] < r) lo = m + 1; else hi = m; } return lo; }
  function pois(l) { const L = Math.exp(-l); let k = 0, p = 1; do { k++; p *= Math.random(); } while (p > L); return k - 1; }
  function timeline(gh, ga, xh, xa) {
    const ev = []; for (let i = 0; i < NSLOT; i++) ev.push({ shot: null, red: null, redDone: false });
    const slot = () => { for (let k = 0; k < 5000; k++) { const i = Math.floor(Math.random() * NSLOT); if (!ev[i].shot && Math.random() < (0.85 + 0.35 * i / 96) / 1.2) return i; } return -1; };
    const put = (team, goal) => { const i = slot(); if (i < 0) return; let xg, pen = false;
      if (goal) { if (Math.random() < 0.073) { xg = 0.76; pen = true; } else for (;;) { const u = Math.random(); xg = 0.025 + 0.55 * u ** 5; if (Math.random() < xg / 0.575) break; } }
      else for (;;) { const u = Math.random(); xg = 0.025 + 0.55 * u ** 5; if (Math.random() < 1 - xg) break; }
      let out = "goal"; if (!goal) { const o = Math.random(); out = o < 0.40 ? "saved" : o < 0.78 ? "off" : "blocked"; }
      ev[i].shot = { team, xg, pen, goal, out, done: false }; };
    for (let k = 0; k < gh; k++) put(0, true); for (let k = 0; k < ga; k++) put(1, true);
    const nh = Math.min(30, pois(Math.max(0.5, xh / XGM - xh))), na = Math.min(30, pois(Math.max(0.5, xa / XGM - xa)));
    for (let k = 0; k < nh; k++) put(0, false); for (let k = 0; k < na; k++) put(1, false);
    let rh = 0, ra = 0; for (let i = 0; i < NSLOT; i++) { const r = Math.random(); if (r < RED && !rh) { ev[i].red = 0; rh = 1; } else if (r >= RED && r < 2 * RED && !ra) { ev[i].red = 1; ra = 1; } }
    return ev;
  }
  function summarise(c, n, G) {
    let h = 0, d = 0, a = 0, o15 = 0, o25 = 0, o35 = 0, btts = 0, sgh = 0, sga = 0; const cells = [];
    for (let x = 0; x < G; x++) for (let y = 0; y < G; y++) { const p = c[x * G + y] / n; if (!p) continue;
      if (x > y) h += p; else if (x === y) d += p; else a += p;
      if (x + y > 1) o15 += p; if (x + y > 2) o25 += p; if (x + y > 3) o35 += p; if (x && y) btts += p;
      sgh += x * p; sga += y * p; cells.push([x, y, p]); }
    cells.sort((p, q) => q[2] - p[2]);
    return { h, d, a, o15, o25, o35, btts, sgh, sga, top: cells.slice(0, 6) };
  }

  // ---------------------------------------------------------------- formations
  const DEFAULT_LINES = [4, 3, 3];
  function lineY(k, j) { return k === 1 ? 34 : 8 + 52 * (j + 0.5) / k; }
  // -> 11 players {bx, by, role, num, name}; real XI in its formation when the forecast has one.
  function squad(lu) {
    const st = (lu && lu.starters) || [];
    let lines = String((lu && lu.formation) || "").split("-").map(Number).filter((n) => n > 0);
    let gkp = null, outf = [];
    if (st.length === 11) { const gi = Math.max(0, st.findIndex((p) => p.pos === "G")); gkp = st[gi]; outf = st.filter((_, i) => i !== gi); }
    if (lines.reduce((a, b) => a + b, 0) !== 10) {
      if (outf.length === 10 && outf.every((p) => "DMF".includes(p.pos || "?"))) {
        const ord = { D: 0, M: 1, F: 2 }; outf = outf.slice().sort((p, q) => ord[p.pos] - ord[q.pos]);
        lines = ["D", "M", "F"].map((g) => outf.filter((p) => p.pos === g).length).filter((n) => n > 0);
      } else lines = DEFAULT_LINES;
    }
    const real = outf.length === 10;
    const out = [{ bx: 5, by: 34, role: "G", num: gkp && gkp.shirt != null ? gkp.shirt : 1, name: gkp ? gkp.name : "" }];
    let k = 0;
    lines.forEach((n, li) => { const bx = lines.length === 1 ? 40 : 20 + li * 40 / (lines.length - 1);
      for (let j = 0; j < n; j++, k++) { const p = real ? outf[k] : null, edge = n > 2 && (j === 0 || j === n - 1) ? 2 : 0;
        out.push({ bx: bx + (li === 0 ? edge : li === lines.length - 1 ? -edge : edge), by: lineY(n, j), role: li === 0 ? "D" : li === lines.length - 1 ? "F" : "M",
          num: p && p.shirt != null ? p.shirt : k + 2, name: p ? p.name : "" }); } });
    return { players: out, formation: lines.join("-"), real };
  }
  const surname = (n) => { const t = String(n || "").trim().split(/\s+/); return t[t.length - 1] || ""; };

  // ---------------------------------------------------------------- state
  let FCS = [], CUR = null, MARKET = {}, MK = { h: "", d: "", a: "" }, RES = null, running = false, P = [], G = null, SQ = [null, null];
  const useLu = () => $("sim-lineups").checked;
  function active() {
    if (!CUR) return null;
    const s = CUR.simulation, ls = CUR.lineup_simulation || {}, on = useLu() && ls.applied && ls.score_grid;
    const src = on ? ls : s;
    return { grid: src.score_grid, xh: src.xg_home, xa: src.xg_away, lineups: !!on, key: (CUR.fixture.event_id || CUR.fixture.home_name) + "|" + (on ? "L" : "T") + "|" + (CUR.frozen_at || "") };
  }
  const names = () => [CUR.fixture.home_name, CUR.fixture.away_name];

  // ---------------------------------------------------------------- 100,000 runs
  function runSims() {
    const a = active(); if (!a || running) return; running = true;
    const Gn = a.grid.length, counts = new Int32Array(Gn * Gn), cdf = gridCdf(a.grid); let done = 0; const t0 = performance.now();
    $("sim-run").disabled = true; $("sim-info").textContent = "Running…"; $("sim-prog").style.width = "0";
    (function step() {
      for (let j = 0; j < 10000; j++) counts[sampleGrid(cdf)]++;
      done += 10000; $("sim-prog").style.width = done / N_SIMS * 100 + "%";
      if (done < N_SIMS) { setTimeout(step, 0); return; }
      running = false; $("sim-run").disabled = false;
      const now = active(); if (!now || now.key !== a.key) { runSims(); return; }
      RES = { s: summarise(counts, N_SIMS, Gn), counts, G: Gn, key: a.key };
      $("sim-info").textContent = N_SIMS.toLocaleString() + " matches in " + ((performance.now() - t0) / 1000).toFixed(1) + " s" + (a.lineups ? " · line-ups applied" : " · tested forecast");
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
    const fin = G && G.done && G.key === RES.key ? [Math.min(5, G.score[0]), Math.min(5, G.score[1])] : null;
    let h = '<div class="hd"></div>' + [0, 1, 2, 3, 4, "5+"].map((v) => `<div class="hd">${v}</div>`).join("");
    for (let x = 0; x < 6; x++) { h += `<div class="hd">${x === 5 ? "5+" : x}</div>`;
      for (let y = 0; y < 6; y++) { const p = cell(x, y); h += `<div class="c${fin && fin[0] === x && fin[1] === y ? " me" : ""}" style="background:rgba(214,156,8,${(p / mx * 0.75).toFixed(3)})">${(p * 100).toFixed(1)}</div>`; } }
    $("sim-heat").innerHTML = h;
    $("sim-heat-note").textContent = "Rows are " + hn + " goals, columns are " + an + " goals, values in percent." + (fin ? " The outlined box is the match you just watched." : "");
    $("sim-top").innerHTML = s.top.map(([x, y, p]) => `<tr><td class="l">${esc(hn)} ${x} – ${y} ${esc(an)}</td><td>${pct(p)}</td></tr>`).join("");
  }

  // ---------------------------------------------------------------- watched match
  const cv = $("sim-pitch"), cx = cv.getContext("2d"), S = 12, MG = 30, X = (x) => MG + x * S, Y = (y) => MG + y * S;
  const COL = ["#d69c08", "#fef9e0"], BEAT = 0.36;
  const label = (i) => { if (i < 45) return i + 1 + "'"; if (i < H1) return "45+" + (i - 44) + "'"; const m = 46 + (i - H1); return m <= 90 ? m + "'" : "90+" + (m - 90) + "'"; };
  const base = (p) => (p.team ? [105 - p.bx, 68 - p.by] : [p.bx, p.by]);
  function makePlayers() {
    const lus = (CUR && CUR.context && CUR.context.lineups) || {};
    SQ = [squad(lus.home), squad(lus.away)]; P = [];
    SQ.forEach((sq, t) => sq.players.forEach((q, i) => { const p = { ...q, team: t, idx: i, off: false, carry: false, f: 0.5 + Math.random() * 0.6, ph: Math.random() * 6.3 }; [p.x, p.y] = base(p); P.push(p); }));
  }
  const gk = (t) => P[t * 11];
  function nearest(team, x, y, allowGK, not) { let best = null, bd = 1e9; for (const p of P) { if (p.team !== team || p.off || p === not || (!allowGK && p.idx === 0)) continue; const d = (p.x - x) ** 2 + (p.y - y) ** 2; if (d < bd) { bd = d; best = p; } } return best; }
  function kickoff(team) {
    for (const p of P) { const b = base(p); p.x = p.team ? Math.max(b[0], 54.5) : Math.min(b[0], 50.5); p.y = b[1]; p.carry = false; }
    const k = nearest(team, 52.5, 34, false) || gk(team);
    k.x = 52.5 + (team ? 0.6 : -0.6); k.y = 34; G.holder = k; G.poss = team; G.ball.x = 52.5; G.ball.y = 34;
  }
  function resetView() {
    if (G) G.playing = false; G = null; makePlayers(); draw();
    const [hn, an] = CUR ? names() : ["Home", "Away"];
    $("sim-home").textContent = hn; $("sim-away").textContent = an; $("sim-score").textContent = "0 – 0"; $("sim-clock").textContent = "Kick-off";
    $("sim-skip").disabled = true; $("sim-play").textContent = "Play match"; $("sim-live").textContent = "Press Play match to watch one simulated game.";
    $("sim-feed").innerHTML = '<li class="muted">Goals and red cards appear here.</li>'; stats([0, 0], [0, 0], ["0.00", "0.00"]);
  }
  function stats(a, b, c) { $("sim-stats").innerHTML = [["Shots", a], ["On target", b], ["Chance quality (xG)", c]].map(([n, v]) => `<div class="l">${v[0]}</div><div class="m">${n}</div><div class="r">${v[1]}</div>`).join(""); }
  function newMatch() {
    const a = active(); if (!a) return; makePlayers();
    const cdf = gridCdf(a.grid), k = sampleGrid(cdf), Gn = a.grid.length, sc = clampN(a.xh / (a.xh + a.xa), 0.35, 0.65);
    G = { tl: timeline((k / Gn) | 0, k % Gn, a.xh, a.xa), minute: -1, queue: [], cur: null, stepT: 0, score: [0, 0], shots: [0, 0], sot: [0, 0], xg: [0, 0],
      playing: true, done: false, holder: null, poss: 0, ball: { x: 52.5, y: 34 }, names: names(), time: 0, flash: 0, key: a.key, pTurn: [0.42 * (1 - sc), 0.42 * sc], last: performance.now() };
    kickoff(0);
    $("sim-feed").innerHTML = '<li class="muted">Goals and red cards appear here.</li>'; $("sim-live").textContent = "Kick-off.";
    $("sim-skip").disabled = false; $("sim-play").textContent = "Restart match"; board(); requestAnimationFrame(frame);
  }
  function board() { $("sim-score").textContent = G.score[0] + " – " + G.score[1]; $("sim-clock").textContent = G.done ? "Full time" : G.minute < 0 ? "Kick-off" : label(G.minute); stats(G.shots, G.sot, G.xg.map((v) => v.toFixed(2))); }
  function feed(t, txt) { const f = $("sim-feed"); if (f.firstChild && f.firstChild.className === "muted") f.innerHTML = ""; const li = document.createElement("li"); li.innerHTML = `<span class="t">${t}</span><span>${esc(txt)}</span>`; f.prepend(li); }
  function pickShooter(t) {
    const c = P.filter((p) => p.team === t && !p.off && p.idx !== 0), w = c.map((p) => (p.role === "F" ? 5 : p.role === "M" ? 2.5 : 0.5));
    let r = Math.random() * w.reduce((a, b) => a + b, 0); for (let j = 0; j < c.length; j++) { r -= w[j]; if (r <= 0) return c[j]; } return c[0];
  }
  function applyShot(e, i) {
    if (e.done) return; e.done = true; const t = e.team, n = G.names[t], who = e.by && e.by.name ? surname(e.by.name) + " (" + n + ")" : n;
    G.shots[t]++; G.xg[t] += e.xg; if (e.out === "goal" || e.out === "saved") G.sot[t]++;
    const q = " Chance " + Math.round(e.xg * 100) + "%.";
    if (e.goal) { G.score[t]++; G.flash = 1.6; feed(label(i), "Goal" + (e.pen ? " from a penalty" : "") + ": " + who + ". " + G.names[0] + " " + G.score[0] + " – " + G.score[1] + " " + G.names[1] + "." + q); $("sim-live").textContent = label(i) + " Goal: " + who + "!"; }
    else $("sim-live").textContent = label(i) + " " + who + (e.pen ? " penalty " : " shot ") + (e.out === "saved" ? "saved." : e.out === "off" ? "off target." : "blocked.") + q;
    board();
  }
  function applyRed(ev, i) {
    if (ev.redDone) return; ev.redDone = true; const c = P.filter((p) => p.team === ev.red && !p.off && p.idx !== 0 && p !== G.holder && !p.carry && p !== G.shooter);
    const p = c[Math.floor(Math.random() * c.length)]; if (p) p.off = true;
    const who = p && p.name ? surname(p.name) + " (" + G.names[ev.red] + ")" : G.names[ev.red];
    feed(label(i), "Red card: " + who + "."); $("sim-live").textContent = label(i) + " Red card: " + who + ".";
  }
  function pickReceiver(h) {
    const dir = h.team ? -1 : 1, toGoal = dir > 0 ? 105 - h.x : h.x, c = []; let tot = 0;
    for (const p of P) { if (p.team !== h.team || p === h || p.off) continue; const dx = (p.x - h.x) * dir, dist = Math.hypot(p.x - h.x, p.y - h.y); if (dist < 3) continue;
      let w = Math.exp(-dist / 20) * (dx > 0 ? 1.7 : 0.7); if (p.idx === 0) w *= 0.15; if (toGoal < 22 && dx > 0) w *= 0.3; c.push([p, w]); tot += w; }
    if (!c.length) return h; let r = Math.random() * tot; for (const [p, w] of c) { r -= w; if (r <= 0) return p; } return c[0][0];
  }
  const ease = (t) => t * t * (3 - 2 * t);
  function passTo(to, dur) { const fx = G.ball.x, fy = G.ball.y; G.holder = null; return { dur: dur || 1, update(t) { const e = ease(t); G.ball.x = fx + (to.x - fx) * e; G.ball.y = fy + (to.y - fy) * e; }, end() { G.holder = to; G.poss = to.team; } }; }
  function carry(p, tx, ty, dur) { const sx = p.x, sy = p.y; p.carry = true; return { dur, update(t) { p.x = sx + (tx - sx) * t; p.y = sy + (ty - sy) * t; }, end() { p.carry = false; } }; }
  const hold = (dur) => ({ dur, update() {}, end() {} });
  function resolve(s) {
    const i = G.minute;
    if (s.k === "hold") { if (s.msg) $("sim-live").textContent = s.msg; return hold(s.dur); }
    if (s.k === "kickoff") { kickoff(s.team); return hold(0.4); }
    if (s.k === "goalkick") { G.holder = gk(s.team); G.poss = s.team; return hold(0.5); }
    if (!G.holder) G.holder = nearest(G.poss, G.ball.x, G.ball.y, true);
    const h = G.holder, dir = h.team ? -1 : 1, toGoal = dir > 0 ? 105 - h.x : h.x;
    if (s.k === "play") {
      if (Math.random() < 0.18 && toGoal > 30 && h.idx !== 0) return carry(h, clampN(h.x + dir * (4 + Math.random() * 4), 2, 103), clampN(h.y + (Math.random() - 0.5) * 6, 2, 66), 1);
      const rc = pickReceiver(h); if (rc === h) return hold(1);
      if (Math.random() < G.pTurn[h.team] + (toGoal < 25 ? 0.25 : 0)) return passTo(nearest(1 - h.team, rc.x, rc.y, true) || rc);
      return passTo(rc);
    }
    const e = s.e, t = e.team;
    if (s.k === "toShooter") {
      const sh = pickShooter(t); G.shooter = sh; e.by = sh;
      if (h.team !== t) { G.holder = nearest(t, G.ball.x, G.ball.y, false, sh) || sh; G.poss = t; }
      return G.holder === sh ? hold(0.3) : passTo(sh);
    }
    const sh = G.shooter, d2 = t ? -1 : 1;
    if (s.k === "carryShot") { G.holder = sh; G.poss = t; const d = e.pen ? 11 : 7 + (1 - Math.min(e.xg, 0.6) / 0.6) * 21;
      return carry(sh, d2 > 0 ? 105 - d : d, e.pen ? 34 : clampN(34 + (Math.random() * 2 - 1) * (6 + d * 0.35), 4, 64), 1.6); }
    const fx = G.ball.x, fy = G.ball.y, gx = d2 > 0 ? 105 : 0, opp = 1 - t; G.holder = null; let tgt, blocker = null;
    if (e.out === "goal") tgt = { x: gx + 1.3 * d2, y: 34 + (Math.random() * 2 - 1) * 2.8 };
    else if (e.out === "saved") tgt = gk(opp);
    else if (e.out === "off") tgt = { x: gx + 2.2 * d2, y: 34 + (Math.random() < 0.5 ? -1 : 1) * (5.5 + Math.random() * 4.5) };
    else { blocker = nearest(opp, sh.x + d2 * 3, sh.y, false) || gk(opp); tgt = blocker; }
    return { dur: 0.8, update(u) { G.ball.x = fx + (tgt.x - fx) * u; G.ball.y = fy + (tgt.y - fy) * u; }, end() {
      applyShot(e, i); G.shooter = null;
      if (e.out === "goal") G.queue.push({ k: "hold", dur: 4 }, { k: "kickoff", team: opp });
      else if (e.out === "saved") { G.holder = gk(opp); G.poss = opp; }
      else if (e.out === "off") G.queue.push({ k: "goalkick", team: opp });
      else { G.holder = blocker; G.poss = opp; }
    } };
  }
  function plan(i) {
    const ev = G.tl[i];
    if (i === H1) G.queue.push({ k: "hold", dur: 4, msg: "Half time. " + G.names[0] + " " + G.score[0] + " – " + G.score[1] + " " + G.names[1] }, { k: "kickoff", team: 1 });
    if (ev.red !== null) applyRed(ev, i);
    if (ev.shot) G.queue.push({ k: "toShooter", e: ev.shot }, { k: "carryShot", e: ev.shot }, { k: "shoot", e: ev.shot });
    else G.queue.push({ k: "play" }, { k: "play" }, { k: "play" });
    board();
  }
  function nextStep() { while (!G.queue.length) { G.minute++; if (G.minute >= NSLOT) { finish(); return; } plan(G.minute); } G.cur = resolve(G.queue.shift()); G.stepT = 0; }
  function finish() {
    G.playing = false; G.done = true; G.cur = null; $("sim-skip").disabled = true; $("sim-play").textContent = "Play another match";
    const sc = G.names[0] + " " + G.score[0] + " – " + G.score[1] + " " + G.names[1]; feed("FT", "Full time. " + sc + "."); let msg = "Full time. " + sc + ".";
    if (RES && RES.key === G.key) { const c = RES.counts[Math.min(RES.G - 1, G.score[0]) * RES.G + Math.min(RES.G - 1, G.score[1])] / N_SIMS; msg += " This score came up in " + pct(c) + " of the 100,000 simulations."; renderResults(); }
    $("sim-live").textContent = msg; board(); draw();
  }
  function skip() {
    if (!G || !G.playing) return;
    for (let i = Math.max(0, G.minute); i < NSLOT; i++) { const e = G.tl[i]; if (e.red !== null) applyRed(e, i); if (e.shot) { if (!e.shot.by) e.shot.by = pickShooter(e.shot.team); applyShot(e.shot, i); } }
    G.minute = NSLOT; G.flash = 0; G.queue = []; for (const p of P) p.carry = false; kickoff(0); G.holder = null; finish();
  }
  function movePlayers(dts) {
    const b = G.ball, pr = G.holder ? nearest(1 - G.poss, b.x, b.y, false) : null, k = Math.min(1, dts * 2.2);
    for (const p of P) { if (p.off || p.carry) continue; const dir = p.team ? -1 : 1, bs = base(p); let tx, ty;
      if (p.idx === 0) { tx = bs[0] + (b.x - 52.5) * 0.1; ty = 34 + (b.y - 34) * 0.12; }
      else if (p === G.holder) { tx = p.x + dir * 2; ty = p.y; }
      else if (p === pr) { tx = b.x + (p.x > b.x ? 1.6 : -1.6); ty = b.y; }
      else { tx = bs[0] + (b.x - 52.5) * 0.5 + (G.poss === p.team ? 5 : -3) * dir + Math.sin(G.time * p.f + p.ph) * 1.3; ty = bs[1] + (b.y - 34) * 0.3 + Math.cos(G.time * p.f * 0.8 + p.ph) * 1.3; }
      p.x += (clampN(tx, 2, 103) - p.x) * k; p.y += (clampN(ty, 2, 66) - p.y) * k; }
    if (G.holder) { b.x = G.holder.x + (G.holder.team ? -1.1 : 1.1); b.y = G.holder.y; }
  }
  function frame(now) {
    if (!G || !G.playing) return; const me = G;
    const dt = Math.min(0.05, (now - G.last) / 1000); G.last = now;
    const dts = dt * parseFloat($("sim-speed").value); G.time += dts; if (G.flash > 0) G.flash -= dts;
    if (!G.cur) nextStep();
    if (G.playing && G.cur) { G.stepT += dts / (BEAT * G.cur.dur);
      if (G.stepT < 1) G.cur.update(G.stepT); else { G.cur.update(1); G.cur.end(); G.cur = null; nextStep(); } }
    if (G !== me || !G.playing) return;
    movePlayers(dts); draw(); requestAnimationFrame(frame);
  }
  function draw() {
    const c = cx; c.fillStyle = "#1f6b3f"; c.fillRect(0, 0, cv.width, cv.height);
    for (let i = 0; i < 10; i += 2) { c.fillStyle = "#24764a"; c.fillRect(X(i * 10.5), Y(0), 10.5 * S, 68 * S); }
    c.strokeStyle = "rgba(255,255,255,.85)"; c.lineWidth = 3; c.strokeRect(X(0), Y(0), 105 * S, 68 * S);
    c.beginPath(); c.moveTo(X(52.5), Y(0)); c.lineTo(X(52.5), Y(68)); c.stroke();
    c.beginPath(); c.arc(X(52.5), Y(34), 9.15 * S, 0, 7); c.stroke();
    c.strokeRect(X(0), Y(13.85), 16.5 * S, 40.3 * S); c.strokeRect(X(88.5), Y(13.85), 16.5 * S, 40.3 * S);
    c.strokeRect(X(0), Y(24.85), 5.5 * S, 18.3 * S); c.strokeRect(X(99.5), Y(24.85), 5.5 * S, 18.3 * S);
    c.strokeRect(X(-1.8), Y(30.34), 1.8 * S, 7.32 * S); c.strokeRect(X(105), Y(30.34), 1.8 * S, 7.32 * S);
    c.fillStyle = "rgba(255,255,255,.85)"; for (const px of [11, 52.5, 94]) { c.beginPath(); c.arc(X(px), Y(34), 4, 0, 7); c.fill(); }
    c.textAlign = "center"; c.textBaseline = "middle";
    for (const p of P) { if (p.off) continue; const hl = G && p === G.holder;
      c.beginPath(); c.arc(X(p.x), Y(p.y), 17, 0, 7); c.fillStyle = COL[p.team]; c.fill(); c.lineWidth = hl ? 5 : 2.5; c.strokeStyle = hl ? "#fff" : "#06140c"; c.stroke();
      c.fillStyle = "#161000"; c.font = "700 17px system-ui, sans-serif"; c.fillText(p.num, X(p.x), Y(p.y) + 1);
      if (p.name) { c.font = "600 15px system-ui, sans-serif"; c.lineWidth = 4; c.strokeStyle = "rgba(4,30,16,.85)"; const n = surname(p.name).slice(0, 12); c.strokeText(n, X(p.x), Y(p.y) + 30); c.fillStyle = "#fff"; c.fillText(n, X(p.x), Y(p.y) + 30); } }
    const b = G ? G.ball : { x: 52.5, y: 34 };
    c.beginPath(); c.arc(X(b.x), Y(b.y), 8, 0, 7); c.fillStyle = "#fff"; c.fill(); c.lineWidth = 2.5; c.strokeStyle = "#111"; c.stroke();
    if (G && G.flash > 0) { c.fillStyle = "rgba(1,20,25,.5)"; c.fillRect(0, 0, cv.width, cv.height); c.fillStyle = "#f9d731"; c.font = "800 150px system-ui, sans-serif"; c.fillText("GOAL", cv.width / 2, cv.height / 2); }
  }

  // ---------------------------------------------------------------- match picker and line-up note
  const BADGE = { confirmed: "confirmed", projected: "projected (not confirmed yet)", inferred: "estimated from recent minutes", none: "not available" };
  function note() {
    if (!CUR) { $("sim-lineup-note").textContent = ""; $("sim-xi").innerHTML = ""; return; }
    const lus = (CUR.context && CUR.context.lineups) || {}, ls = CUR.lineup_simulation, [hn, an] = names();
    const side = (sd, nm, i) => `${esc(nm)}: ${BADGE[(lus[sd] || {}).status || "none"]}${SQ[i] && SQ[i].real ? ", " + esc(SQ[i].formation) : ""}`;
    let eff;
    if (!ls) eff = `<b class="off">Not in this forecast yet.</b> It was frozen before line-ups were added to the simulator; the next model run adds them. Using the tested forecast.`;
    else if (!ls.applied) eff = `<b class="off">Probabilities unchanged.</b> ${esc(ls.reason)}`;
    else if (!useLu()) eff = `<b class="off">Switched off.</b> Using the tested forecast.`;
    else { const m = (v) => (v == null ? "" : "×" + Number(v).toFixed(3)); eff = `<b class="on">Applied.</b> ${esc(hn)} goals ${m(ls.home_rate_mult)}, ${esc(an)} goals ${m(ls.away_rate_mult)}. ${esc(ls.note || "")}`; }
    $("sim-lineup-note").innerHTML = `<b>Line-ups.</b> ${side("home", hn, 0)} · ${side("away", an, 1)}.<br>${eff}`;
    $("sim-xi").innerHTML = [0, 1].map((i) => `<div><b>${esc(names()[i])}</b> ${SQ[i].real ? esc(SQ[i].formation) : ""}<div class="muted small">${SQ[i].real ? SQ[i].players.map((p) => esc(p.num + " " + p.name)).join(", ") : "No starting eleven published yet. Shown in a default 4-3-3."}</div></div>`).join("");
  }
  function marketFor(fc) {
    const e = MARKET[fc.fixture.event_id]; if (!e) return { h: "", d: "", a: "" }; const o = { h: "", d: "", a: "" };
    for (const r of e.rows || []) { if (r.market !== "1X2" || r.market_mid == null) continue; const k = r.selection === e.home ? "h" : r.selection === e.away ? "a" : /draw/i.test(r.selection) ? "d" : null; if (k) o[k] = (r.market_mid * 100).toFixed(1); }
    return o;
  }
  function pick(id) {
    CUR = FCS.find((f) => String(f.fixture.event_id) === String(id)) || null; RES = null;
    if (CUR) MK = marketFor(CUR);
    resetView(); note();
    if (CUR) runSims(); else { $("sim-info").textContent = ""; ["sim-bar", "sim-odds", "sim-kv", "sim-heat", "sim-top"].forEach((i) => ($(i).innerHTML = "")); $("sim-heat-note").textContent = ""; }
  }
  const tm = (iso) => (iso ? new Date(iso).toLocaleString("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit" }) : "");
  window.Sim = {
    setForecasts(res) {
      FCS = (res.forecasts || []).filter((f) => f.status === "ok" && f.simulation && f.simulation.score_grid);
      const sel = $("sim-match"), keep = CUR && CUR.fixture.event_id;
      sel.innerHTML = FCS.length ? FCS.map((f) => `<option value="${esc(f.fixture.event_id)}">${esc(tm(f.fixture.kickoff_utc) + " · " + f.fixture.home_name + " v " + f.fixture.away_name + " (" + f.fixture.competition + ")")}</option>`).join("") : '<option value="">No simulated matches on this date</option>';
      const now = Date.now(), withLu = (f) => f.lineup_simulation && f.lineup_simulation.applied;
      const first = FCS.find((f) => String(f.fixture.event_id) === String(keep)) || FCS.find((f) => withLu(f) && Date.parse(f.fixture.kickoff_utc) > now) || FCS.find((f) => Date.parse(f.fixture.kickoff_utc) > now) || FCS[0];
      if (first) sel.value = first.fixture.event_id; pick(sel.value);
    },
    setMarket(events) { MARKET = Object.fromEntries((events || []).map((e) => [e.event_id, e])); if (CUR && !MK.h && !MK.d && !MK.a) { MK = marketFor(CUR); renderResults(); } },
    open(id) { const sel = $("sim-match"); if ([...sel.options].some((o) => o.value === String(id))) { sel.value = id; pick(id); } },
  };
  $("sim-match").addEventListener("change", () => pick($("sim-match").value));
  $("sim-lineups").addEventListener("change", () => { note(); resetView(); runSims(); });
  $("sim-play").addEventListener("click", newMatch); $("sim-skip").addEventListener("click", skip); $("sim-run").addEventListener("click", runSims);
  makePlayers(); draw(); stats([0, 0], [0, 0], ["0.00", "0.00"]);
})();
