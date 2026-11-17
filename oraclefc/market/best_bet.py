"""POST-HOC best bet per game (runs only after forecasts are frozen; never feeds the model).

For every buyable Polymarket selection on a full-time goals market we can price from the
frozen score grid, compute

    market mid         = (best ask + best bid) / 2                 (two-sided CLOB book)
    bet probability    = mid + SHRINK_W * (p_model - mid)          (model shrunk toward the market)
    cost per contract  = ask + Polymarket taker fee                (taker: you pay the ask)
    EV per $1 staked   = bet probability / cost - 1

WHY THE SHRINK (review of 2026-11-16, 328 settled bets): selections averaged model 62.2%,
ask 53.1%, and won 48.8% (-9.8% ROI). Where the raw model and the market disagreed, the market
was right, and the largest raw edges were the worst calibrated. The raw model probability is
therefore no longer used as the bet probability.

A selection is ELIGIBLE only if ALL hold:
  * p_model > 0.50 and EV > 0 after fees using the SHRUNK probability;
  * raw edge (p_model - ask) <= MAX_RAW_EDGE (bigger disagreements are treated as model error);
  * market kind is not in EXCLUDED_KINDS (team totals and BTTS lost most per bet);
  * traded volume >= MIN_VOLUME and a two-sided book no wider than 10c, 90-minute contract.
The best bet is the eligible selection with the highest EV; otherwise the game is "NO BET".

Fees: Polymarket taker fee = rate * (p * (1 - p)) ** exponent per contract, read from each
market's own ``feeSchedule`` (https://docs.polymarket.com/trading/fees). When a market exposes
no schedule the documented sports rate (0.05, exponent 1) is assumed and flagged.
"""
from __future__ import annotations

import math
import re

import numpy as np

FEES = {
    "polymarket": {"taker_rate": 0.05, "exponent": 1.0,
                   "source": "docs.polymarket.com/trading/fees (per-market feeSchedule; sports default shown)"},
}
DEFAULT_FEE = "polymarket"
MIN_P, MIN_EV = 0.50, 0.0
SHRINK_W = 0.50          # weight on the model; 1 - SHRINK_W on the market mid
MAX_RAW_EDGE = 0.08      # p_model - ask above this is never bet
MIN_VOLUME = 500.0       # contracts traded on the market
EXCLUDED_KINDS = frozenset({"team_total", "btts"})
SELECTION_POLICY = "market-shrink-w50-edgecap8-core-v5"
EXACT_RE = re.compile(r"^(?P<h>.+?)\s+(?P<hg>\d+)\s*-\s*(?P<ag>\d+)\s+(?P<a>.+)$")
HCP_RE = re.compile(r"([+-]\d+(?:\.\d+)?)\s*$")


def fee_per_contract(price: float, provider: str | None = "polymarket", fee: dict | None = None) -> float:
    """Taker fee for one contract bought at ``price``. ``fee`` is the market's own {rate, exponent}."""
    if fee and fee.get("rate") is not None:
        rate, exponent = float(fee["rate"]), float(fee.get("exponent", 1.0))
    else:
        f = FEES.get((provider or "").lower(), FEES[DEFAULT_FEE])
        rate, exponent = f["taker_rate"], f["exponent"]
    return rate * ((price * (1 - price)) ** exponent)


def ev_per_dollar(p: float, price: float, provider: str | None = "polymarket", fee: dict | None = None) -> float:
    return p / (price + fee_per_contract(price, provider, fee)) - 1.0


def bet_probability(p_model: float, ask: float, bid) -> float | None:
    """Model probability shrunk toward the market mid. None without a usable two-sided quote."""
    if not (isinstance(bid, (int, float)) and math.isfinite(bid) and 0 < bid <= ask < 1):
        return None
    mid = (ask + bid) / 2
    return mid + SHRINK_W * (p_model - mid)


# ------------------------------------------------------------------ market -> outcome specs
def _usd(x):
    return (x or 0) / 1e6


def _side(m, outcome, label, side, ask, bid, provider):
    return {"market_id": m.get("marketId"), "market_type": m.get("sportsMarketType"), "label": label,
            "side": side, "outcome": outcome, "ask": ask, "bid": bid or None,
            "volume": (m.get("pricing") or {}).get("volume"), "provider": provider, "fee": m.get("fee"),
            "regulation_only": bool(re.search(r"\b90\s+minutes?\b", m.get("rulesPrimary") or "", re.I)
                                    and "stoppage" in (m.get("rulesPrimary") or "").lower())}


def selections_from_event(ev: dict, home: str, away: str) -> list[dict]:
    """Every buyable side (YES and NO) of every full-time goals market we can price."""
    out = []
    for m in ev.get("markets") or []:
        if m.get("periodType") or m.get("status") != "open":
            continue
        t, title = m.get("sportsMarketType"), (m.get("title") or "").strip()
        pr = m.get("pricing") or {}
        provider = (m.get("provider") or "").lower() or None
        team = (m.get("team") or {}).get("name") if isinstance(m.get("team"), dict) else None
        side_of = {home: "home", away: "away"}
        spec, label = None, None
        if t == "moneyline" and not m.get("isTeamMarket"):
            res = "D" if title.lower() == "draw" else {"home": "H", "away": "A"}.get(side_of.get(title))
            if res:
                spec, label = {"kind": "1x2", "res": res}, ("Draw" if res == "D" else f"{title} to win")
        elif t == "both_teams_to_score":
            spec, label = {"kind": "btts"}, "Both teams to score"
        elif t in ("totals", "soccer_team_totals") and title in ("Over", "Under") and m.get("sportsLine") is not None:
            line = float(m["sportsLine"])
            if line % 1 != 0.5:
                continue  # whole-number lines can push; not modelled
            if t == "totals":
                spec, label = {"kind": "total", "line": line, "over": title == "Over"}, f"{title} {line:g} goals"
            elif team in side_of:
                spec = {"kind": "team_total", "team": side_of[team], "line": line, "over": title == "Over"}
                label = f"{team} {title.lower()} {line:g} goals"
        elif t == "spreads" and team in side_of:
            opts = m.get("marketOptions") or [{}]
            h = HCP_RE.search(opts[0].get("label") or "")
            if h and float(h.group(1)) % 1 == 0.5:
                hcp = float(h.group(1))
                spec, label = {"kind": "spread", "team": side_of[team], "hcp": hcp}, f"{team} {hcp:+g}"
        elif t == "soccer_exact_score":
            em = EXACT_RE.match(title)
            if em and em.group("h") in side_of and em.group("a") in side_of and em.group("h") != em.group("a"):
                g = {side_of[em.group("h")]: int(em.group("hg")), side_of[em.group("a")]: int(em.group("ag"))}
                spec, label = {"kind": "exact", "h": g["home"], "a": g["away"]}, f"Exact score {g['home']}-{g['away']}"
        if spec is None:
            continue
        ay, by_ = _usd(pr.get("buyYesPriceUsd")), _usd(pr.get("sellYesPriceUsd"))
        an, bn = _usd(pr.get("buyNoPriceUsd")), _usd(pr.get("sellNoPriceUsd"))
        if 0 < ay < 1:
            out.append(_side(m, spec, label, "YES", ay, by_, provider))
        if 0 < an < 1:
            out.append(_side(m, {**spec, "neg": True}, _neg_label(spec, label, home, away), "NO", an, bn, provider))
    return out


def _neg_label(spec, label, home, away):
    k = spec["kind"]
    if k == "1x2":
        return {"H": f"{away} or draw (NO on {home})", "A": f"{home} or draw (NO on {away})",
                "D": "Either team to win (NO on draw)"}[spec["res"]]
    if k == "btts":
        return "Both teams to score — NO"
    if k == "exact":
        return f"Any score except {spec['h']}-{spec['a']}"
    return f"NO — {label}"


def _grid(score_grid) -> np.ndarray:
    g = np.asarray(score_grid, float)
    return g / g.sum()


def model_prob(spec: dict, score_grid, sim: dict | None = None) -> float:
    """P(outcome) from the frozen forecast. Headline numbers (1X2, BTTS, totals) are taken from the
    simulation summary itself so the card and the bet agree; everything else from the score grid."""
    p = _from_sim(spec, sim) if sim else None
    if p is not None:
        return 1.0 - p if spec.get("neg") else p
    g = _grid(score_grid)
    n = g.shape[0]
    H, A = np.meshgrid(np.arange(n), np.arange(n), indexing="ij")
    k = spec["kind"]
    if k == "1x2":
        mask = {"H": H > A, "D": H == A, "A": H < A}[spec["res"]]
    elif k == "btts":
        mask = (H > 0) & (A > 0)
    elif k == "total":
        mask = (H + A) > spec["line"] if spec["over"] else (H + A) < spec["line"]
    elif k == "team_total":
        G = H if spec["team"] == "home" else A
        mask = G > spec["line"] if spec["over"] else G < spec["line"]
    elif k == "spread":
        diff = (H - A) if spec["team"] == "home" else (A - H)
        mask = diff + spec["hcp"] > 0
    elif k == "exact":
        mask = (H == spec["h"]) & (A == spec["a"])
    else:
        raise ValueError(k)
    p = float(g[mask].sum())
    return 1.0 - p if spec.get("neg") else p


def _from_sim(spec, sim):
    k = spec["kind"]
    if k == "1x2":
        return sim.get({"H": "p_home", "D": "p_draw", "A": "p_away"}[spec["res"]])
    if k == "btts":
        return sim.get("btts")
    if k == "total":
        o = (sim.get("totals_over") or {}).get(f"over_{spec['line']:g}")
        return None if o is None else (o if spec["over"] else 1.0 - o)
    return None


def score_supports(spec, score):
    if not isinstance(score, dict): return False
    h, a = score.get('home'), score.get('away')
    if any(isinstance(x, bool) or not isinstance(x, (int, np.integer)) or x < 0 for x in (h,a)): return False
    try:
        k = spec['kind']
        if k == '1x2': win = {'H': h>a, 'D': h==a, 'A': a>h}[spec['res']]
        elif k == 'btts': win = h>0 and a>0
        elif k in ('total','team_total'):
            v = h+a if k == 'total' else h if spec['team']=='home' else a
            if v == spec['line']: return False
            win = v>spec['line'] if spec['over'] else v<spec['line']
        elif k == 'spread':
            d = (h-a if spec['team']=='home' else a-h) + spec['hcp']
            if d == 0: return False
            win = d>0
        elif k == 'exact': win = h==spec['h'] and a==spec['a']
        else: return False
        return bool(not win if spec.get('neg') else win)
    except (KeyError, TypeError, ValueError): return False


def evaluate(selections: list[dict], score_grid, sim: dict | None = None) -> list[dict]:
    rows = []
    for s in selections:
        p = model_prob(s["outcome"], score_grid, sim)
        fee = fee_per_contract(s["ask"], s.get("provider"), s.get("fee"))
        cost = s["ask"] + fee
        bid = s.get("bid")
        thin = not (isinstance(bid, (int, float)) and math.isfinite(bid)
                    and 0 < bid <= s["ask"] and s["ask"] - bid <= 0.10 + 1e-9)
        bet_p = bet_probability(p, s["ask"], bid)
        raw_ev = p / cost - 1.0
        ev = (bet_p / cost - 1.0) if bet_p is not None else raw_ev
        volume = s.get("volume")
        liquid = isinstance(volume, (int, float)) and math.isfinite(volume) and volume >= MIN_VOLUME
        consistent = score_supports(s["outcome"], (sim or {}).get("modal_score"))
        raw_edge = p - s["ask"]
        excluded = s["outcome"]["kind"] in EXCLUDED_KINDS
        fee_known = bool(s.get("fee")) and (s["fee"].get("source") != "assumed")
        valid = bool(not thin and liquid and s.get("regulation_only") is True)
        rows.append({**s, "score_consistent": consistent, "model_p": p, "bet_p": bet_p, "market_mid": (s["ask"] + bid) / 2 if not thin else None,
                     "fee_per_contract": fee, "cost_per_contract": cost,
                     "ev_per_dollar": ev, "raw_ev_per_dollar": raw_ev, "edge_pp": 100 * raw_edge, "thin_book": bool(thin),
                     "fee_assumed": not fee_known, "excluded_market": excluded, "edge_capped": bool(raw_edge > MAX_RAW_EDGE + 1e-12),
                     "quote_valid": valid,
                     "eligible": bool(valid and consistent and not excluded and raw_edge <= MAX_RAW_EDGE + 1e-12
                                      and bet_p is not None and p > MIN_P and ev > MIN_EV)})
    return rows


def best_bet(selections: list[dict], score_grid, sim: dict | None = None, *, components: dict | None = None) -> dict:
    rows = evaluate(selections, score_grid, sim)
    primary = sorted((components or {}).items(), key=lambda item: item[1].get("weight", 0), reverse=True)[:2]
    blocked = []
    if len(primary) == 2:
        for row in rows:
            spec = row["outcome"]
            if spec["kind"] != "1x2":
                continue
            probabilities = {name: model_prob(spec, score_grid, component) for name, component in primary}
            row["component_probabilities"] = probabilities
            row["component_min_p"] = min(probabilities.values())
            row["component_max_p"] = max(probabilities.values())
            row["conservative_ev_per_dollar"] = row["component_min_p"] / row["cost_per_contract"] - 1
            threshold = max(MIN_P, row["cost_per_contract"])
            if row["eligible"] and row["component_min_p"] <= threshold:
                row["eligible"] = False
                blocked.append(row)
    elig = sorted((r for r in rows if r["eligible"]), key=lambda r: (-r["ev_per_dollar"], -r["model_p"]))
    out = {"n_priced": len(rows), "n_eligible": len(elig),
           "selection_policy": SELECTION_POLICY,
           "rule": (f"model P > {MIN_P:.0%}; EV > 0 at the Polymarket ask incl. fees using the model shrunk {1 - SHRINK_W:.0%} toward the market mid; "
                    f"raw edge <= {MAX_RAW_EDGE * 100:.0f} pts; no team totals or BTTS; volume >= {MIN_VOLUME:.0f}; "
                    "bet must win at displayed predicted score; highest EV wins")}
    if not elig:
        out["verdict"] = "NO BET"
        if blocked:
            out["reason"] = "main model components do not both clear 50% and after-fee break-even"
        if rows and not any(r["quote_valid"] for r in rows):
            out["reason"] = f"no verified two-sided 90-minute quote with at least {MIN_VOLUME:.0f} traded volume"
        elif rows and not blocked and any(r["quote_valid"] and r["edge_capped"] and r["model_p"] > MIN_P for r in rows):
            out["reason"] = f"model disagrees with the market by more than {MAX_RAW_EDGE * 100:.0f} pts; treated as model error, not edge"
        cands = [r for r in rows if r["quote_valid"] and r["score_consistent"] and not r["excluded_market"] and not r["edge_capped"]
                 and r["model_p"] > MIN_P and r not in blocked]
        if cands:  # closest miss, for transparency
            out["closest"] = _public(max(cands, key=lambda r: r["ev_per_dollar"]))
        return out
    out["verdict"] = "BET"
    out["bet"] = _public(elig[0])
    out["alternatives"] = [_public(r) for r in elig[1:3]]
    return out


def _public(r: dict) -> dict:
    keys = ("score_consistent", "market_id", "market_type", "label", "side", "ask", "bid", "volume", "model_p", "bet_p", "market_mid",
            "fee_per_contract", "cost_per_contract", "ev_per_dollar", "raw_ev_per_dollar", "edge_pp", "thin_book", "fee_assumed")
    out = {k: (round(r[k], 6) if isinstance(r[k], float) else r[k]) for k in keys}
    for key in ("component_probabilities", "component_min_p", "component_max_p", "conservative_ev_per_dollar"):
        if key in r:
            out[key] = r[key]
    if r.get("outcome") is not None:
        out["outcome"] = r["outcome"]  # settlement spec, used by post-match grading
    return out
