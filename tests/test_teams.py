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


def test_espanyol_is_never_barcelona_and_missing_known_identity_is_rejected():
    assert match_team('RCD Espanyol de Barcelona', ['Barcelona', 'Espanol']).canonical == 'Espanol'
    assert match_team('RCD Espanyol de Barcelona', ['Barcelona']).canonical is None
    assert match_team('RCD Espanyol de Barcelona', ['Espanyol']).canonical == 'Espanyol'
    assert match_team('Imaginary Barcelona FC', ['Barcelona']).canonical is None
    assert match_team('Unrecognised Sporting Lisbon FC', ['Sp Lisbon']).canonical is None


def test_verified_compound_names_preserve_coverage_without_city_containment():
    cases={'FC Energie Cottbus':'Cottbus','SC Corinthians Paulista':'Corinthians',
           'DSC Arminia Bielefeld':'Bielefeld','SV Zulte Waregem':'Waregem',
           'Clube do Remo':'Remo','Red Bull Bragantino':'Bragantino','1. FSV Mainz 05':'Mainz',
           'Borussia M.Gladbach':"M'gladbach",'Clermont Foot':'Clermont'}
    for source,canonical in cases.items():
        assert match_team(source,list(cases.values())).canonical==canonical


def test_ambiguous_fuzzy_match_does_not_depend_on_candidate_order():
    for names in [['Teston','Testan'],['Testan','Teston']]:
        m=match_team('Testen',names,threshold=.8)
        assert m.canonical is None and m.method=='ambiguous'
