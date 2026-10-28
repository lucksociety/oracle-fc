"""Map a discovered fixture (team names + competition) to rated teams."""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from . import config, store
from .teams import match_team

EURO_COMPS = {"ucl", "uel", "ucol"}


@dataclass
class Resolved:
    home_name: str
    away_name: str
    home: str | None = None
    away: str | None = None
    home_key: str | None = None
    away_key: str | None = None
    home_div: str | None = None
    away_div: str | None = None
    div: str | None = None
    country: str | None = None
    neutral: bool = False
    notes: list[str] = field(default_factory=list)
    match_methods: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return bool(self.home_key and self.away_key)


class Resolver:
    def __init__(self, df: pd.DataFrame):
        self.df = df
        dom = df[df["div"] != "UCL"]
        recent = dom[dom["date"] >= dom["date"].max() - pd.Timedelta(days=500)]
        last = pd.concat([
            recent[["date", "home", "home_key", "div", "country"]].rename(columns={"home": "name", "home_key": "key"}),
            recent[["date", "away", "away_key", "div", "country"]].rename(columns={"away": "name", "away_key": "key"}),
        ]).sort_values("date").groupby("key").tail(1)
        self.by_key = last.set_index("key")
        self.by_div: dict[str, list[tuple[str, str]]] = {}
        for r in last.itertuples(index=False):
            self.by_div.setdefault(r.div, []).append((r.name, r.key))

    def _lookup(self, name: str, divs: list[str]):
        cands = [(n, k) for d in divs for (n, k) in self.by_div.get(d, [])]
        names = [n for n, _ in cands]
        m = match_team(name, names)
        if m.canonical is None:
            return None, m
        keys = [k for n, k in cands if n == m.canonical]
        if len(keys) != 1:
            return None, m
        return keys[0], m

    def resolve(self, home_name: str, away_name: str, subcategory: str = "", neutral: bool = False) -> Resolved:
        sub = (subcategory or "").lower()
        divs = config.JUPITER_SUBCATEGORY_DIVS.get(sub)
        r = Resolved(home_name, away_name, neutral=neutral)
        if divs is None:
            r.notes.append(f"UNSUPPORTED competition '{subcategory}': no free historical results source is "
                           "ingested for it, so no forecast is produced.")
            r.match_methods = {"home": {"source": home_name, "matched": None, "method": "unsupported-competition"},
                               "away": {"source": away_name, "matched": None, "method": "unsupported-competition"}}
            return r
        for side, name in (("home", home_name), ("away", away_name)):
            key, m = self._lookup(name, divs)
            if key is None and sub not in EURO_COMPS:
                # e.g. cup ties against teams outside the mapped divisions
                key2, m2 = self._lookup(name, [d for d in self.by_div if config.ALL_DIVISIONS.get(d, ("",))[0]
                                               == config.ALL_DIVISIONS.get(divs[0], ("?",))[0]])
                if key2 and m2.method in ("exact", "alias", "normalised"):
                    key, m = key2, m2
            r.match_methods[side] = {"source": name, "matched": m.canonical if key else None,
                                     "method": m.method if key else "unmatched", "score": m.score}
            if key is None:
                r.notes.append(f"UNMATCHED team: '{name}' has no rated record in the permitted data "
                               f"(competition '{subcategory}'); no forecast is produced rather than guessing.")
                continue
            info = self.by_key.loc[key]
            setattr(r, side, info["name"])
            setattr(r, f"{side}_key", key)
            setattr(r, f"{side}_div", info["div"])
        if r.ok:
            if sub in EURO_COMPS:
                r.div, r.country = "UCL", "Europe"
                if sub != "ucl":
                    r.notes.append("Europa/Conference League: modelled with the Champions League home-advantage and "
                                   "scoring environment (no UEL/UECL results ingested yet).")
            else:
                r.div = r.home_div
                r.country = config.ALL_DIVISIONS.get(r.home_div, ("Europe",))[0]
                if r.home_div != r.away_div:
                    r.notes.append(f"Cross-division tie ({r.home_div} vs {r.away_div}); strengths are linked through "
                                   "promotion/relegation and European results.")
        return r

    def fixture_frame(self, r: Resolved) -> pd.DataFrame:
        return pd.DataFrame([{"home_key": r.home_key, "away_key": r.away_key, "div": r.div,
                              "home_div": r.home_div, "away_div": r.away_div, "country": r.country,
                              "neutral": r.neutral}])

    def last_match_date(self, key: str):
        return self.by_key.loc[key, "date"]
