from oraclefc.ingest.openfootball_cl import parse_cl_text

TXT = """= UEFA Champions League 2025/26

▪ League, Matchday 1
  Tue Sep 16 2025
    18:45  Athletic Club (ESP)     v Arsenal FC (ENG)         0-2 (0-0)
  Wed Sep 17
           PAE Olympiakos SFP (GRE) v Paphos FC (CYP)          0-0
▪ Playoffs
  Tue Feb 24
           Juventus FC (ITA)       v Galatasaray SK (TUR)     3-2 a.e.t. (3-0, 1-0)
▪ Finals, Final
  Sat May 30
    18:00  Paris Saint-Germain FC (FRA) v Arsenal FC (ENG)         4-3 pen. 1-1 a.e.t. (1-1, 0-1)
           Future FC (ENG) v Other FC (ESP)
"""


def test_parse_scores_years_and_extra_time():
    df = parse_cl_text(TXT, "2025-26")
    assert len(df) == 4
    assert df.iloc[0]["date"].year == 2025 and df.iloc[2]["date"].year == 2026
    assert (df.iloc[0]["hg"], df.iloc[0]["ag"]) == (0, 2)
    assert (df.iloc[1]["hg"], df.iloc[1]["ag"]) == (0, 0)
    assert (df.iloc[2]["hg"], df.iloc[2]["ag"]) == (3, 0)      # 90-minute score
    assert (df.iloc[3]["hg"], df.iloc[3]["ag"]) == (1, 1)
    assert bool(df.iloc[3]["neutral"]) and not bool(df.iloc[0]["neutral"])
