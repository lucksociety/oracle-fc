"""Team-strength goal models (Model A family).

One implementation covers three configurations:

* ``standard_poisson``  – static attack/defence Poisson, flat weights, no rho
* ``standard_dc``       – static Dixon–Coles (adds low-score dependence rho)
* ``dynamic_dc``        – time-weighted (exponential decay) Dixon–Coles with
                          hierarchical partial pooling of each team toward its
                          division mean (MAP estimate of a Bayesian model).

The fit is *global*: all divisions plus UEFA Champions League results are fitted
jointly, so teams from different leagues are connected through promotion/
relegation and European fixtures (cross-league translation). Team strengths
are therefore on a common scale and cup/European ties can be priced.

log λ_home = μ + home_c·(1−neutral) + att_h − def_a
log λ_away = μ + att_a − def_h
Prior: att_t ~ N(A_div(t), 1/κ), def_t ~ N(D_div(t), 1/κ)  (hierarchical)
       or N(0, 1/κ) (non-hierarchical).
Rho is fitted after the rates (two-stage, weighted 1-D likelihood).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import minimize, minimize_scalar

from .base import GoalModel


class TeamStrengthModel(GoalModel):
    def __init__(self, name: str = "dynamic_dc", half_life_days: float | None = 240.0,
                 window_days: int = 1100, kappa: float = 6.0, hierarchical: bool = True,
                 use_rho: bool = True):
        self.name = name
        self.half_life_days = half_life_days
        self.window_days = window_days
        self.kappa = kappa
        self.hierarchical = hierarchical
        self.use_rho = use_rho
        self.x0 = None

    # ----------------------------------------------------------------- fit
    def fit(self, df: pd.DataFrame, as_of):
        as_of = pd.Timestamp(as_of)
        d = self._train(df, as_of, self.window_days)
        teams = pd.Index(sorted(set(d["home_key"]).union(d["away_key"])))
        dom = d[d["div"] != "UCL"]
        last_div = {}
        for k, dv in zip(dom["home_key"], dom["div"]):
            last_div[k] = dv
        for k, dv in zip(dom["away_key"], dom["div"]):
            last_div[k] = dv
        divs = pd.Index(sorted(set(last_div.values()) | {"UCL_ONLY"}))
        team_div = np.array([divs.get_loc(last_div.get(t, "UCL_ONLY")) for t in teams])
        groups = pd.Index(sorted(d["country"].unique()))
        hi = teams.get_indexer(d["home_key"])
        ai = teams.get_indexer(d["away_key"])
        gi = groups.get_indexer(d["country"])
        nonneutral = (~d["neutral"].to_numpy(bool)).astype(float)
        yh = d["hg"].to_numpy(float)
        ya = d["ag"].to_numpy(float)
        if self.half_life_days:
            age = (as_of - d["date"]).dt.days.to_numpy(float)
            w = 0.5 ** (age / self.half_life_days)
        else:
            w = np.ones(len(d))
        T, Dv, Gc = len(teams), len(divs), len(groups)
        kap, hier = self.kappa, self.hierarchical

        sl = {"att": slice(0, T), "def": slice(T, 2 * T), "home": slice(2 * T, 2 * T + Gc),
              "A": slice(2 * T + Gc, 2 * T + Gc + Dv), "D": slice(2 * T + Gc + Dv, 2 * T + Gc + 2 * Dv),
              "mu": slice(2 * T + Gc + 2 * Dv, 2 * T + Gc + 2 * Dv + 1)}
        npar = 2 * T + Gc + 2 * Dv + 1

        def f(x):
            att, dfn, home = x[sl["att"]], x[sl["def"]], x[sl["home"]]
            A, D, mu = x[sl["A"]], x[sl["D"]], x[sl["mu"]][0]
            eta_h = mu + home[gi] * nonneutral + att[hi] - dfn[ai]
            eta_a = mu + att[ai] - dfn[hi]
            lh, la = np.exp(eta_h), np.exp(eta_a)
            nll = -np.sum(w * (yh * eta_h - lh + ya * eta_a - la))
            eh, ea = w * (lh - yh), w * (la - ya)
            g = np.zeros(npar)
            g[sl["att"]] = np.bincount(hi, eh, T) + np.bincount(ai, ea, T)
            g[sl["def"]] = -np.bincount(ai, eh, T) - np.bincount(hi, ea, T)
            g[sl["home"]] = np.bincount(gi, eh * nonneutral, Gc)
            g[sl["mu"]] = eh.sum() + ea.sum()
            if hier:
                ra, rd = att - A[team_div], dfn - D[team_div]
                nll += 0.5 * kap * (ra @ ra + rd @ rd) + 0.5 * 1e-2 * (A @ A + D @ D)
                g[sl["att"]] += kap * ra
                g[sl["def"]] += kap * rd
                g[sl["A"]] = -kap * np.bincount(team_div, ra, Dv) + 1e-2 * A
                g[sl["D"]] = -kap * np.bincount(team_div, rd, Dv) + 1e-2 * D
            else:
                nll += 0.5 * kap * (att @ att + dfn @ dfn) + 0.5 * (A @ A + D @ D)
                g[sl["att"]] += kap * att
                g[sl["def"]] += kap * dfn
                g[sl["A"]] = A
                g[sl["D"]] = D
            nll += 0.5 * 0.1 * (home @ home)
            g[sl["home"]] += 0.1 * home
            return nll, g

        x0 = np.zeros(npar)
        x0[sl["mu"]] = np.log(max(np.average((yh + ya) / 2, weights=w), 0.1))
        x0[sl["home"]] = 0.2
        res = minimize(f, x0, jac=True, method="L-BFGS-B", options={"maxiter": 3000, "gtol": 1e-6})
        x = res.x
        self.teams, self.divs, self.groups = teams, divs, groups
        self.att = pd.Series(x[sl["att"]], teams)
        self.dfn = pd.Series(x[sl["def"]], teams)
        self.home = pd.Series(x[sl["home"]], groups)
        self.A = pd.Series(x[sl["A"]], divs)
        self.D = pd.Series(x[sl["D"]], divs)
        self.mu = float(x[sl["mu"]][0])
        self.team_div = pd.Series(divs[team_div], teams)
        self.converged = bool(res.success)
        # approximate posterior sd of each team's attack / defence (diagonal Laplace)
        lh = np.exp(self.mu + self.home.to_numpy()[gi] * nonneutral + self.att.to_numpy()[hi] - self.dfn.to_numpy()[ai])
        la = np.exp(self.mu + self.att.to_numpy()[ai] - self.dfn.to_numpy()[hi])
        info_att = np.bincount(hi, w * lh, T) + np.bincount(ai, w * la, T) + kap
        info_def = np.bincount(ai, w * lh, T) + np.bincount(hi, w * la, T) + kap
        self.sd_att = pd.Series(1 / np.sqrt(info_att), teams)
        self.sd_def = pd.Series(1 / np.sqrt(info_def), teams)
        self.n_matches_weighted = pd.Series(np.bincount(hi, w, T) + np.bincount(ai, w, T), teams)
        self.rho = 0.0
        if self.use_rho:
            low = (yh <= 1) & (ya <= 1)
            lh_l, la_l, yh_l, ya_l, w_l = lh[low], la[low], yh[low], ya[low], w[low]

            def rho_nll(r):
                t = np.where((yh_l == 0) & (ya_l == 0), 1 - lh_l * la_l * r,
                     np.where((yh_l == 0) & (ya_l == 1), 1 + lh_l * r,
                     np.where((yh_l == 1) & (ya_l == 0), 1 + la_l * r, 1 - r)))
                if np.any(t <= 0):
                    return 1e12
                # normalising constant of the DC-adjusted matrix
                z = 1 - lh * la * r * np.exp(-lh - la) + lh * r * np.exp(-lh - la) * la \
                    + la * r * np.exp(-lh - la) * lh - r * lh * la * np.exp(-lh - la)
                return -np.sum(w_l * np.log(t)) + np.sum(w * np.log(z))

            self.rho = float(minimize_scalar(rho_nll, bounds=(-0.25, 0.25), method="bounded").x)
        self.as_of = as_of
        return self

    # ------------------------------------------------------------- predict
    def _team_params(self, key, div_hint):
        if key in self.att.index:
            return self.att[key], self.dfn[key], self.sd_att[key], self.sd_def[key], True
        if self.hierarchical and div_hint in self.A.index:
            # unseen team: division prior mean with prior uncertainty
            s = 1 / np.sqrt(self.kappa)
            return self.A[div_hint], self.D[div_hint], s, s, False
        return np.nan, np.nan, np.nan, np.nan, False

    def rates(self, fx):
        lh, la, sh, sa = (np.full(len(fx), np.nan) for _ in range(4))
        for i, r in enumerate(fx.itertuples(index=False)):
            hdiv = getattr(r, "home_div", None) or r.div
            adiv = getattr(r, "away_div", None) or r.div
            ah, dh, sah, sdh, _ = self._team_params(r.home_key, hdiv)
            aa, da, saa, sda, _ = self._team_params(r.away_key, adiv)
            country = getattr(r, "country", None)
            home = 0.0 if r.neutral else float(self.home.get(country, self.home.mean()))
            lh[i] = np.exp(self.mu + home + ah - da)
            la[i] = np.exp(self.mu + aa - dh)
            sh[i] = np.sqrt(sah ** 2 + sda ** 2)
            sa[i] = np.sqrt(saa ** 2 + sdh ** 2)
        self._last_sd = (sh, sa)
        return lh, la, np.full(len(fx), self.rho if self.use_rho else 0.0)

    def rate_sd(self, fx):
        self.rates(fx)
        return self._last_sd


def standard_poisson():
    return TeamStrengthModel("standard_poisson", half_life_days=None, window_days=365, kappa=0.5,
                             hierarchical=False, use_rho=False)


def standard_dc():
    return TeamStrengthModel("standard_dc", half_life_days=None, window_days=365, kappa=0.5,
                             hierarchical=False, use_rho=True)


def dynamic_dc(half_life_days: float = 240.0, kappa: float = 6.0):
    return TeamStrengthModel("dynamic_dc", half_life_days=half_life_days, window_days=1100, kappa=kappa,
                             hierarchical=True, use_rho=True)
