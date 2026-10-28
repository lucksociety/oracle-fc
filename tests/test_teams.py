from oraclefc.teams import match_team

CANDS = ["Man City", "Man United", "Brighton", "Celta", "Celta B", "Hearts", "Kelty Hearts", "Vallecano",
         "Sociedad", "Sociedad B", "Bayern Munich", "M'gladbach", "Inter", "Milan", "Fortuna Sittard"]


def test_known_mappings():
    cases = {"Manchester City FC": "Man City", "Manchester United FC": "Man United",
             "Brighton & Hove Albion FC": "Brighton", "Heart of Midlothian FC": "Hearts",
             "Rayo Vallecano de Madrid": "Vallecano", "FC Bayern München": "Bayern Munich",
             "Borussia Mönchengladbach": "M'gladbach", "FC Internazionale Milano": "Inter",
             "Real Sociedad de Fútbol B": "Sociedad B", "Celta Fortuna": "Celta B", "AC Milan": "Milan"}
    for src, want in cases.items():
        assert match_team(src, CANDS).canonical == want, src


def test_unknown_team_is_reported_unmatched_not_guessed():
    m = match_team("CDA Navalcarnero", CANDS)
    assert m.canonical is None and m.method == "unmatched"


def test_reserve_never_maps_to_first_team():
    assert match_team("Celta Vigo B", ["Celta"]).canonical is None
