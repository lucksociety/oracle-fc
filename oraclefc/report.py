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
    L += ["", "DATA QUALITY", ""] + [f"- {d}" for d in fc["data_quality"]]
    L += ["", "FINAL VERDICT", "", fc["verdict"]]
    return "\n".join(L) + "\n"
