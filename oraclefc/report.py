"""Phase 12 standard report renderer. Contains no market information."""
from __future__ import annotations


def pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def render(fc: dict) -> str:
    if fc.get("status") != "ok":
        return ("ORACLE FC — MATCH FORECAST\n\n"
                f"Fixture: {fc['fixture']['away_name']} at {fc['fixture']['home_name']}\n"
                f"Competition: {fc['fixture'].get('competition', '')}\n"
                f"STATUS: NO FORECAST — {'; '.join(fc.get('data_quality', []))}\n")
    s, fx = fc["simulation"], fc["fixture"]
    h, a = fx["home_name"], fx["away_name"]
    ms = s["modal_score"]
    L = ["ORACLE FC — MATCH FORECAST", "",
         f"Fixture: {a} at {h}", f"Competition: {fx.get('competition', '')}",
         f"Date: {fx.get('kickoff_local', fx.get('kickoff_utc', ''))}",
         f"Model Version: {fc['model_version']}", f"Data Cutoff: {fc['data_cutoff']}", "",
         "PRIMARY FINAL SCORE PREDICTION", "", f"{h} {ms['home']} – {ms['away']} {a}",
         f"(modal exact score, probability {pct(ms['p'])}; not rounded expected goals)", "",
         "EXPECTED GOALS", "", f"Home: {s['xg_home']:.2f}", f"Away: {s['xg_away']:.2f}",
         f"Expected Total: {s['xg_total']:.2f}", f"Median Total: {s['median_total']}", "",
         "RESULT PROBABILITIES", "", f"Home Win: {pct(s['p_home'])}", f"Draw: {pct(s['p_draw'])}",
         f"Away Win: {pct(s['p_away'])}", "", "FIVE MOST LIKELY EXACT SCORES", ""]
    for i, t in enumerate(s["top_scores"], 1):
        L.append(f"{i}. {t['home']}–{t['away']}: {pct(t['p'])}")
    b = s["total_buckets"]
    L += ["", "GOALS PROBABILITIES", "", f"Total 0–1 goals: {pct(b['0-1'])}", f"Total 2 goals: {pct(b['2'])}",
          f"Total 3 goals: {pct(b['3'])}", f"Total 4 goals: {pct(b['4'])}", f"Total 5+ goals: {pct(b['5+'])}", "",
          f"Both Teams Score: {pct(s['btts'])}",
          f"Clean sheet {h}: {pct(s['clean_sheet_home'])} · Clean sheet {a}: {pct(s['clean_sheet_away'])}", "",
          "MATCH INTELLIGENCE", ""]
    for i, f in enumerate(fc["key_factors"], 1):
        L.append(f"{i}. {f['text']}")
    c = fc["confidence"]
    L += ["", "MODEL CONFIDENCE", "", c["text"]]
    u = fc.get("uncertainty", {})
    if u:
        L.append(f"Parameter-uncertainty 80% bands: xG {h} {u['xg_home_80'][0]:.2f}–{u['xg_home_80'][1]:.2f}, "
                 f"xG {a} {u['xg_away_80'][0]:.2f}–{u['xg_away_80'][1]:.2f}; "
                 f"P(home win) {pct(u['p_home_80'][0])}–{pct(u['p_home_80'][1])}.")
    mc = fc.get("monte_carlo", {})
    if mc:
        L.append(f"Monte Carlo check: {mc['n_sims']:,} sims, max |MC − exact| = {mc['max_abs_dev_vs_exact']:.4f} "
                 f"(sampling error only; it does not measure model error).")
    L += context_section(fc)
    L += ["", "DATA QUALITY", ""] + [f"- {d}" for d in fc["data_quality"]]
    L += ["", "FINAL VERDICT", "", fc["verdict"]]
    return "\n".join(L) + "\n"


def _ts(x) -> str:
    """UTC ISO -> America/New_York label (reports are read in the user's zone)."""
    if not x:
        return "?"
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from . import config
        return datetime.fromisoformat(str(x).replace("Z", "+00:00")).astimezone(ZoneInfo(config.USER_TZ)).strftime(
            "%Y-%m-%d %H:%M %Z")
    except Exception:
        return str(x)


def context_section(fc: dict) -> list[str]:
    c = fc.get("context")
    if not c:
        return []
    fx = fc["fixture"]
    names = {"home": fx.get("home_matched") or fx["home_name"], "away": fx.get("away_matched") or fx["away_name"]}
    L = ["", "LINEUPS", ""]
    for side in ("home", "away"):
        x = (c.get("lineups") or {}).get(side) or {}
        st = (x.get("status") or "none").upper()
        src = f" — {x['source']}" if x.get("source") else ""
        when = f", fetched {_ts(x.get('fetched_at'))}" if x.get("fetched_at") else ""
        L.append(f"{names[side]}: {st}{src}{when}" + (f" ({x['formation']})" if x.get("formation") else ""))
        if x.get("starters"):
            L.append("  " + ", ".join(f"{p['name']} ({p.get('pos') or '?'})" for p in x["starters"]))
        if x.get("n_configurations"):
            L.append(f"  {x['n_configurations']} XI configuration(s) simulated · XI attack index vs recent XIs "
                     f"{x.get('mean_xi_attack_index', 0):+.3f} (log) · continuity {x.get('mean_continuity', 0):+.2f} · "
                     f"P(backup GK) {x.get('p_backup_gk', 0):.0%}")
        if x.get("note"):
            L.append(f"  {x['note']}")
    L += ["", "KEY ABSENCES", ""]
    any_ab = False
    for side in ("home", "away"):
        for a in (c.get("absences") or {}).get(side, []):
            any_ab = True
            extra = f", {a['chance_of_playing']}% chance of playing" if a.get("chance_of_playing") is not None else ""
            news = f" — FPL: {a['fpl_news']} (updated {_ts(a.get('fpl_news_added'))})" if a.get("fpl_news") else ""
            L.append(f"- {names[side]}: {a['player']} — {a.get('type')}, {a.get('expected_return') or 'return unknown'}"
                     f"{extra} [{a['source']}, {_ts(a.get('fetched_at'))}]{news}")
    if not any_ab:
        L.append("- None listed by the sources.")
    w = c.get("weather")
    L += ["", "WEATHER AT VENUE", ""]
    v = c.get("venue") or {}
    vn = ", ".join(str(x) for x in (v.get("name"), v.get("city")) if x)
    if w:
        L.append(f"{vn}: {w['temp_c']:.1f} °C, wind {w['wind_ms']:.1f} m/s, precipitation {w['precip_mm_2h']:.1f} mm over "
                 f"the two kickoff hours [{w['source']}, fetched {_ts(w['fetched_at'])}]")
    else:
        L.append(f"{vn or 'Venue unknown'}: no forecast available yet.")
    r = c.get("rest") or {}
    h, a = r.get("home") or {}, r.get("away") or {}
    L += ["", "REST & TRAVEL", "",
          f"{names['home']}: {h.get('rest_days', '?')} days' rest, {h.get('n21', '?')} matches in previous 21 days · "
          f"{names['away']}: {a.get('rest_days', '?')} days' rest, {a.get('n21', '?')} in 21 days · away travel "
          f"{(c.get('travel') or {}).get('away_travel_km', '?')} km"]
    L += ["", "HOW EACH FACTOR MOVED THE FORECAST (percentage points vs the team-strength base)", ""]
    b = fc.get("base_simulation")
    if b:
        L.append(f"Base (validated ensemble incl. xG, before context): {pct(b['p_home'])} / {pct(b['p_draw'])} / {pct(b['p_away'])}, "
                 f"xG {b['xg_home']:.2f}–{b['xg_away']:.2f}")
    for sh in c.get("factor_shifts", []):
        if not sh.get("applied"):
            if "d_p_home_pp" in sh:
                L.append(f"- {sh['factor']}: NOT APPLIED (failed out-of-sample validation); would have moved home "
                         f"{sh['d_p_home_pp']:+.2f} pp, draw {sh['d_p_draw_pp']:+.2f} pp, away {sh['d_p_away_pp']:+.2f} pp")
            else:
                L.append(f"- {sh['factor']}: not applied ({sh.get('reason')})")
            continue
        L.append(f"- {sh['factor']}: home {sh['d_p_home_pp']:+.2f} pp, draw {sh['d_p_draw_pp']:+.2f} pp, away "
                 f"{sh['d_p_away_pp']:+.2f} pp; xG {sh['d_xg_home']:+.3f} / {sh['d_xg_away']:+.3f}")
    t = c.get("total_shift")
    if t and any(x.get("applied") for x in c.get("factor_shifts", []) if not x["factor"].startswith("Understat")):
        L.append(f"- ALL APPLIED CONTEXT: home {t['d_p_home_pp']:+.2f} pp, draw {t['d_p_draw_pp']:+.2f} pp, away "
                 f"{t['d_p_away_pp']:+.2f} pp")
    if not any(x.get("applied") for x in c.get("factor_shifts", []) if not x["factor"].startswith("Understat")):
        L.append("- No lineup/injury/rest/travel/weather family passed validation, so none moves the probabilities "
                 "(shown above for transparency only). Final probabilities = validated ensemble incl. xG.")
    return L
