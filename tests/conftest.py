import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def synthetic_matches():
    """Synthetic league with known team strengths (no external data needed)."""
    rng = np.random.default_rng(0)
    teams = [f"T{i}" for i in range(12)]
    att = dict(zip(teams, rng.normal(0, 0.3, 12)))
    dfn = dict(zip(teams, rng.normal(0, 0.3, 12)))
    rows = []
    d = pd.Timestamp("2020-08-01")
    for wk in range(160):
        rng.shuffle(teams)
        for h, a in zip(teams[::2], teams[1::2]):
            lh = np.exp(0.15 + 0.25 + att[h] - dfn[a])
            la = np.exp(0.15 + att[a] - dfn[h])
            rows.append({"date": d + pd.Timedelta(days=7 * wk), "div": "E0", "country": "England",
                         "season": "2021", "home": h, "away": a, "home_key": f"England:{h}",
                         "away_key": f"England:{a}", "hg": int(rng.poisson(lh)), "ag": int(rng.poisson(la)),
                         "neutral": False})
    df = pd.DataFrame(rows)
    df["match_id"] = [f"m{i}" for i in range(len(df))]
    return df
