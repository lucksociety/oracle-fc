"""Phase 11: automated pre-match workflow for one fixture or a whole date.

fixture identity -> team resolution -> point-in-time fit (data < now) ->
component models -> validated ensemble -> exact joint distribution ->
Monte Carlo convergence check -> integrity checks -> report -> freeze.
No market data is read anywhere in this module (enforced by tests).
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from . import __version__, config, frozen, store
from .experiments import load_registry
from .governance import assert_no_price_keys, now_utc_iso
from .models.baselines import HomeAwayRate
from .models.dixon_coles import dynamic_dc, standard_dc
from .models.elo import EloGoals
from .models.ensemble import combine
from .report import render
from .resolve import Resolver
from .simulate import monte_carlo, param_uncertainty, summarise

DEFAULT_WEIGHTS = {"dynamic_dc": 1.0}


class Engine:
    """Fits the champion's component models once on all data available now."""

    def __init__(self, df: pd.DataFrame | None = None, as_of: pd.Timestamp | None = None):
        self.df = df if df is not None else store.load()
        self.cutoff = store.data_cutoff(self.df)
        self.as_of = as_of or (self.df["date"].max() + pd.Timedelta(days=1))
        reg = load_registry()
        ch = reg.get("champion") or {}
        p = ch.get("params", {"half_life_days": 240.0, "kappa": 6.0, "elo_k": 22.0})
        self.champion = ch.get("name", "dynamic_dc")
        self.weights = ch.get("ensemble_weights", DEFAULT_WEIGHTS) if self.champion == "ensemble" else DEFAULT_WEIGHTS
        self.version = ch.get("version", f"{__version__}+dynamic_dc-untuned")
        self.confidence = reg.get("confidence", {})
        self.models = {"dynamic_dc": dynamic_dc(p["half_life_days"], p["kappa"]),
                       "elo": EloGoals(k=p["elo_k"]), "standard_dc": standard_dc(),
                       "home_away_rate": HomeAwayRate()}
        for m in self.models.values():
            m.fit(self.df, self.as_of)
        self.resolver = Resolver(self.df)

    # ------------------------------------------------------------------
    def matrix(self, fx: pd.DataFrame):
        names = list(self.weights)
        mats = [self.models[n].predict_matrix(fx) for n in names]
        w = np.array([self.weights[n] for n in names], float)
        comp = {n: m[0] for n, m in zip(names, mats)}
        return combine(mats, w)[0], comp

    def _key_factors(self, r, fx) -> list[dict]:
        dc = self.models["dynamic_dc"]
        f = []
        att_h, def_h = dc.att.get(r.home_key, np.nan), dc.dfn.get(r.home_key, np.nan)
        att_a, def_a = dc.att.get(r.away_key, np.nan), dc.dfn.get(r.away_key, np.nan)
        if np.isfinite(att_h) and np.isfinite(def_a):
            e = att_h - def_a
            f.append({"effect": abs(e), "text": f"{r.home} attack vs {r.away} defence: time-weighted strength gap "
                      f"multiplies {r.home}'s scoring rate by ×{math.exp(e):.2f} relative to an average pairing "
                      f"(from {dc.n_matches_weighted.get(r.home_key, 0):.0f}/{dc.n_matches_weighted.get(r.away_key, 0):.0f} "
                      "decay-weighted matches)."})
        if np.isfinite(att_a) and np.isfinite(def_h):
            e = att_a - def_h
            f.append({"effect": abs(e), "text": f"{r.away} attack vs {r.home} defence: rate multiplier ×{math.exp(e):.2f} "
                      "for the away side."})
        if not r.neutral:
            hv = float(dc.home.get(r.country, dc.home.mean()))
            f.append({"effect": abs(hv), "text": f"Home advantage ({r.country}, fitted from results): "
                      f"×{math.exp(hv):.2f} on {r.home}'s scoring rate."})
        elo = self.models["elo"]
        rh, ra = elo.rating(r.home_key), elo.rating(r.away_key)
        if np.isfinite(rh) and np.isfinite(ra):
            gap = rh - ra
            f.append({"effect": abs(gap) / 400 * 0.6, "text": f"Independent results-only Elo: {r.home} {rh:.0f} vs "
                      f"{r.away} {ra:.0f} (gap {gap:+.0f} before home advantage)."})
        f.sort(key=lambda x: -x["effect"])
        return [{"text": x["text"], "effect": round(float(x["effect"]), 4)} for x in f[:3]]

    def _confidence(self, s: dict, div: str) -> dict:
        pmax = max(s["p_home"], s["p_draw"], s["p_away"])
        rows = self.confidence.get("overall", [])
        hit = next((r for r in rows if r["lo"] <= pmax < r["hi"] + 1e-9), None)
        dsum = self.confidence.get("by_division", {}).get(div, {}).get("summary")
        overall = self.confidence.get("overall_summary")
        base = self.confidence.get("baseline_summary")
        parts = [f"Most likely result has P = {pmax:.1%}."]
        if hit:
            parts.append(f"In the out-of-sample backtest, favourites priced {hit['lo']:.2f}–{hit['hi']:.2f} won "
                         f"{hit['hit_rate']:.1%} ± {hit['se']:.1%} (n={hit['n']}, mean forecast {hit['mean_pred']:.1%}).")
        if dsum:
            parts.append(f"Backtest RPS for {div}: {dsum['rps']:.4f}; exact-score top-5 hit rate {dsum['top5']:.1%} "
                         f"(n={dsum['n']}).")
        elif overall:
            parts.append(f"No division-specific backtest (n<150); overall backtest RPS {overall['rps']:.4f}.")
        if overall and base:
            parts.append(f"Overall champion RPS {overall['rps']:.4f} vs home/away baseline {base['rps']:.4f}.")
        if not self.confidence:
            parts.append("No backtest registry found — confidence is UNVALIDATED.")
        ent = -sum(p * math.log(p) for p in (s["p_home"], s["p_draw"], s["p_away"]) if p > 0)
        tier = "HIGH" if pmax >= 0.65 else ("MODERATE" if pmax >= 0.5 else "LOW")
        return {"tier": tier, "p_max": pmax, "entropy_nats": ent, "text": " ".join(parts) +
                f" Outcome-certainty tier: {tier} (entropy {ent:.3f} nats of max 1.099)."}

    # ------------------------------------------------------------------
    def forecast(self, home_name: str, away_name: str, competition: str = "", subcategory: str = "",
                 kickoff_utc: str | None = None, event_id: str | None = None, neutral: bool = False,
                 mc_sims: int = 200_000) -> dict:
        r = self.resolver.resolve(home_name, away_name, subcategory, neutral)
        kickoff_local = ""
        if kickoff_utc:
            kickoff_local = datetime.fromisoformat(kickoff_utc).astimezone(ZoneInfo(config.USER_TZ)).strftime(
                "%Y-%m-%d %H:%M %Z")
        fixture = {"event_id": event_id, "home_name": home_name, "away_name": away_name,
                   "competition": competition, "subcategory": subcategory, "kickoff_utc": kickoff_utc,
                   "kickoff_local": kickoff_local, "home_matched": r.home, "away_matched": r.away,
                   "match_methods": r.match_methods, "neutral": neutral}
        base = {"oracle": "ORACLE FC", "model_version": self.version, "champion": self.champion,
                "data_cutoff": self.cutoff, "generated_at": now_utc_iso(), "fixture": fixture}
        dq = list(r.notes)
        if not r.ok:
            return {**base, "status": "unsupported", "data_quality": dq}
        fx = self.resolver.fixture_frame(r)
        m, comps = self.matrix(fx)
        if not np.isfinite(m).all():
            return {**base, "status": "unsupported", "data_quality": dq + ["Component models could not rate this pairing."]}
        s = summarise(m)
        assert abs(s["mass_check"] - 1) < 1e-9
        assert abs(s["p_home"] + s["p_draw"] + s["p_away"] - 1) < 1e-9
        mc = monte_carlo(m, n_sims=mc_sims)
        dc = self.models["dynamic_dc"]
        lh, la, rho = dc.rates(fx)
        sh, sa = dc.rate_sd(fx)
        unc = param_uncertainty(s["xg_home"], s["xg_away"], float(sh[0]), float(sa[0]), float(rho[0]))
        comp_summary = {}
        for n, cm in comps.items():
            if np.isfinite(cm).all():
                cs = summarise(cm)
                comp_summary[n] = {"p_home": cs["p_home"], "p_draw": cs["p_draw"], "p_away": cs["p_away"],
                                   "xg_home": cs["xg_home"], "xg_away": cs["xg_away"], "weight": self.weights[n]}
        # data quality
        for side in ("home", "away"):
            key = getattr(r, f"{side}_key")
            last = self.resolver.last_match_date(key)
            gap = (pd.Timestamp(self.cutoff) - last).days
            nm = dc.n_matches_weighted.get(key, 0.0)
            if gap > 60:
                dq.append(f"{getattr(r, side)}: last ingested match {last.date()} ({gap} days before cutoff) — stale.")
            if nm < 8:
                dq.append(f"{getattr(r, side)}: only {nm:.1f} decay-weighted matches — strength shrunk toward the "
                          "division mean, wide uncertainty.")
        dq += [
            "Lineups, injuries and suspensions: NOT ingested (no verified free point-in-time feed); forecast assumes "
            "typical availability.",
            "Weather, travel and rest days: not modelled (not yet validated out of sample).",
            "Team-level only: no player-level ratings yet; xG is stored for 2026/27 but not used by the champion.",
        ]
        if subcategory in ("cdr", "dfb", "efl", "fac", "cdf", "cit"):
            dq.append("Cup tie: rotation risk is not modelled; cup results are not in the training data.")
        ms = s["modal_score"]
        verdict = (f"{r.home} {ms['home']}–{ms['away']} {r.away} is the single most probable scoreline at "
                   f"{ms['p']:.1%}: expected goals {s['xg_home']:.2f}–{s['xg_away']:.2f} under the "
                   f"{self.champion} model put the joint mode there "
                   f"(DC low-score dependence rho={float(rho[0]):+.3f}). Exact scores are inherently uncertain; "
                   f"the 1X2 split is {s['p_home']:.1%}/{s['p_draw']:.1%}/{s['p_away']:.1%}.")
        out = {**base, "status": "ok", "simulation": s, "monte_carlo": mc, "uncertainty": unc,
               "components": comp_summary, "key_factors": self._key_factors(r, fx),
               "confidence": self._confidence(s, r.div), "data_quality": dq, "verdict": verdict,
               "resolved": {"home_key": r.home_key, "away_key": r.away_key, "div": r.div,
                            "home_div": r.home_div, "away_div": r.away_div, "country": r.country}}
        assert_no_price_keys(out, "forecast output")
        out["report_text"] = render(out)
        return out


def forecast_date(date: str, engine: Engine | None = None, freeze: bool = True, use_cache: bool = True) -> dict:
    """Discover the date's Jupiter soccer fixtures and forecast each one."""
    from .fixtures.jupiter import fixtures_for_date

    engine = engine or Engine()
    fixtures = fixtures_for_date(date, use_cache=use_cache)
    out = []
    for f in fixtures:
        now = datetime.now(timezone.utc)
        existing = [x for x in frozen.load_date(date) if x["fixture"].get("event_id") == f.event_id]
        started = datetime.fromisoformat(f.kickoff_utc) <= now
        if started:
            # never create a forecast after kickoff: only show what was frozen before
            if existing:
                out.append(existing[-1])
            else:
                out.append({"status": "not_forecast_before_kickoff", "fixture": {**f.to_dict()},
                            "data_quality": ["Kick-off passed before any forecast was frozen; none is produced "
                                             "retroactively."]})
            continue
        fc = engine.forecast(f.home_name, f.away_name, f.competition, f.subcategory, f.kickoff_utc, f.event_id)
        if freeze and fc["status"] == "ok":
            fc, _ = frozen.freeze(date, f.event_id, engine.version, fc)
        out.append(fc)
    # Events Jupiter no longer lists (settled / past dates): show what was frozen.
    seen = {f.event_id for f in fixtures}
    for x in frozen.load_date(date):
        if x["fixture"].get("event_id") not in seen:
            out.append(x)
    out.sort(key=lambda x: (x["fixture"].get("kickoff_utc") or "", x["fixture"].get("home_name", "")))
    return {"date": date, "tz": config.USER_TZ, "generated_at": now_utc_iso(), "model_version": engine.version,
            "data_cutoff": engine.cutoff, "n_fixtures": len(fixtures),
            "n_forecast": sum(1 for x in out if x.get("status") == "ok"), "forecasts": out}
