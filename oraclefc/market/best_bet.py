"""POST-HOC best bet per game (runs only after forecasts are frozen; never feeds the model).

For every buyable Jupiter selection on a full-time goals market we can price from the frozen
score grid (1X2, double-chance via NO, BTTS, totals, team totals, spreads/handicaps, exact
score), compute

    cost per contract = ask + Jupiter/Polymarket trading fee      (taker: you pay the ask)
    EV per $1 staked   = p_model / cost - 1
    edge (pp)          = p_model - ask

A selection is ELIGIBLE only if p_model > 0.50 AND EV > 0 after fees. The best bet is the
eligible selection with the highest EV; if none qualifies the game is "NO BET".

Fees (Polymarket-sourced markets on Jupiter Predict, checked 2026-10-28):
  * Jupiter builder fee: 2% of trade value, buys and sells
    (https://docs.jup.ag/user-docs/trade/predict/fees)
  * Polymarket taker fee: C * rate * p * (1 - p), sports rate 0.05, exponent 1, taker only
    (https://docs.polymarket.com/trading/fees; market feeSchedule "sports_fees_v3")
  Jupiter rounds each order's fee UP to the nearest cent, so very small orders pay more than
  the proportional fee used here; EV is quoted for an order large enough that rounding is
  negligible.
"""
from __future__ import annotations

import re

import numpy as np

FEES = {
    "polymarket": {"builder_rate": 0.02, "taker_rate": 0.05, "exponent": 1.0,
                   "source": "docs.jup.ag/user-docs/trade/predict/fees + docs.polymarket.com/trading/fees "
                             "(sports_fees_v3, checked 2026-10-28)"},
}
DEFAULT_FEE = "polymarket"   # unknown routes are charged the Polymarket schedule (conservative) and flagged
MIN_P, MIN_EV = 0.50, 0.0
EXACT_RE = re.compile(r"^(?P<h>.+?)\s+(?P<hg>\d+)\s*-\s*(?P<ag>\d+)\s+(?P<a>.+)$")
HCP_RE = re.compile(r"([+-]\d+(?:\.\d+)?)\s*$")


def fee_per_contract(price: float, provider: str | None = "polymarket") -> float:
    f = FEES.get((provider or "").lower(), FEES[DEFAULT_FEE])
    q = price * (1 - price)
    return f["builder_rate"] * price + f["taker_rate"] * (q ** f["exponent"])


def ev_per_dollar(p_model: float, price: float, provider: str | None = "polymarket") -> float:
    return p_model / (price + fee_per_contract(price, provider)) - 1.0


# ------------------------------------------------------------------ market -> outcome specs
def _usd(x):
    return (x or 0) / 1e6


def _side(m, outcome, label, side, ask, bid, provider):
    return {"market_id": m.get("marketId"), "market_type": m.get("sportsMarketType"), "label": label,
            "side": side, "outcome": outcome, "ask": ask, "bid": bid or None,
            "volume": (m.get("pricing") or {}).get("volume"), "provider": provider}


def selections_from_event(ev: dict, home: str, away: str) -> list[dict]:
    """Every buyable side (YES and NO) of every full-time goals market we can price."""
    out = []
    for m in ev.get("markets") or []:
        if m.get("status") not in (None, "open"):
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


def evaluate(selections: list[dict], score_grid, sim: dict | None = None) -> list[dict]:
    rows = []
    for s in selections:
        p = model_prob(s["outcome"], score_grid, sim)
        fee = fee_per_contract(s["ask"], s.get("provider"))
        ev = p / (s["ask"] + fee) - 1.0
        thin = (not s.get("bid")) or (s["ask"] - (s.get("bid") or 0) > 0.10)
        rows.append({**s, "model_p": p, "fee_per_contract": fee, "cost_per_contract": s["ask"] + fee,
                     "ev_per_dollar": ev, "edge_pp": 100 * (p - s["ask"]), "thin_book": bool(thin),
                     "fee_assumed": (s.get("provider") or "") not in FEES,
                     "eligible": bool(p > MIN_P and ev > MIN_EV)})
    return rows


def best_bet(selections: list[dict], score_grid, sim: dict | None = None) -> dict:
    rows = evaluate(selections, score_grid, sim)
    elig = sorted((r for r in rows if r["eligible"]), key=lambda r: (-r["ev_per_dollar"], -r["model_p"]))
    out = {"n_priced": len(rows), "n_eligible": len(elig),
           "rule": f"model P > {MIN_P:.0%} and EV > 0 at the Jupiter ask incl. fees; highest EV wins"}
    if not elig:
        out["verdict"] = "NO BET"
        cands = [r for r in rows if r["model_p"] > MIN_P]
        if cands:  # closest miss, for transparency
            out["closest"] = _public(max(cands, key=lambda r: r["ev_per_dollar"]))
        return out
    out["verdict"] = "BET"
    out["bet"] = _public(elig[0])
    out["alternatives"] = [_public(r) for r in elig[1:3]]
    return out


def _public(r: dict) -> dict:
    keys = ("market_id", "market_type", "label", "side", "ask", "bid", "volume", "model_p", "fee_per_contract",
            "cost_per_contract", "ev_per_dollar", "edge_pp", "thin_book", "fee_assumed")
    return {k: (round(r[k], 6) if isinstance(r[k], float) else r[k]) for k in keys}
