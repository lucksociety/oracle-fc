"""Team identity resolution between fixture sources (Jupiter, openfootball,
manual input) and the canonical football-data.co.uk team names.

Unmatched teams are *reported*, never guessed: a match below the fuzzy
threshold returns ``None`` and the forecast is marked unsupported.
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass

STOP = {
    "fc", "cf", "afc", "sc", "ssc", "ac", "as", "ss", "us", "sv", "vfl", "vfb", "tsg", "fk", "sk", "if",
    "bk", "club", "de", "the", "cd", "ud", "sd", "rcd", "rc", "ca", "ogc", "losc", "calcio", "1909",
    "1907", "1913", "1846", "1899", "1910", "04", "05", "1860", "1896", "1900", "1901", "1904", "1905",
    "1912", "1919", "1920", "1923", "1927", "1929", "real", "hove", "albion", "and", "&", "football",
    "futbol", "spor", "kulubu", "jk", "kv", "krc", "rsc", "royal", "royale", "sporting", "clube", "sl",
    "pae", "fsv", "bsc", "spvgg", "sg", "aj", "sco", "stade", "es", "esporte", "ec", "se", "cr", "fbc",
    "acf", "asd", "cfc", "gnk", "nk", "pfc", "tc", "town", "city_", "athletic_", "de_", "hotspur", "wanderers", "rovers", "county",
}

# normalised source name -> football-data canonical name (country-qualified where ambiguous)
ALIASES: dict[str, str] = {
    "manchester city": "Man City", "manchester united": "Man United", "man utd": "Man United",
    "tottenham": "Tottenham", "tottenham hotspur": "Tottenham", "wolverhampton": "Wolves",
    "wolverhampton wanderers": "Wolves", "nottingham forest": "Nott'm Forest", "newcastle united": "Newcastle",
    "west ham united": "West Ham", "brighton": "Brighton", "leeds united": "Leeds",
    "sheffield wednesday": "Sheffield Weds", "sheffield united": "Sheffield United", "queens park rangers": "QPR",
    "west bromwich": "West Brom", "west bromwich albion": "West Brom", "preston north end": "Preston",
    "blackburn": "Blackburn", "oxford united": "Oxford", "cambridge united": "Cambridge",
    "milton keynes dons": "Milton Keynes Dons", "mk dons": "Milton Keynes Dons",
    "internazionale milano": "Inter", "internazionale": "Inter", "inter milan": "Inter", "inter": "Inter",
    "milan": "Milan", "roma": "Roma", "lazio": "Lazio", "napoli": "Napoli", "hellas verona": "Verona",
    "bayern munchen": "Bayern Munich", "bayern munich": "Bayern Munich", "borussia dortmund": "Dortmund",
    "borussia monchengladbach": "M'gladbach", "monchengladbach": "M'gladbach", "bayer leverkusen": "Leverkusen",
    "eintracht frankfurt": "Ein Frankfurt", "koln": "FC Koln", "1 koln": "FC Koln", "mainz": "Mainz",
    "hoffenheim": "Hoffenheim", "1899 hoffenheim": "Hoffenheim", "rb leipzig": "RB Leipzig",
    "union berlin": "Union Berlin", "1 union berlin": "Union Berlin", "hertha": "Hertha", "hertha berlin": "Hertha",
    "st pauli": "St Pauli", "1 magdeburg": "Magdeburg", "1 kaiserslautern": "Kaiserslautern",
    "1 nurnberg": "Nurnberg", "1 heidenheim": "Heidenheim", "heidenheim": "Heidenheim",
    "werder bremen": "Werder Bremen", "hamburger": "Hamburg", "hamburg": "Hamburg", "schalke": "Schalke 04",
    "fortuna dusseldorf": "Fortuna Dusseldorf", "greuther furth": "Greuther Furth", "darmstadt": "Darmstadt",
    "atletico madrid": "Ath Madrid", "atletico de madrid": "Ath Madrid", "athletic": "Ath Bilbao",
    "athletic bilbao": "Ath Bilbao", "betis": "Betis", "real betis": "Betis", "betis balompie": "Betis",
    "sociedad": "Sociedad", "real sociedad": "Sociedad", "celta vigo": "Celta", "celta": "Celta",
    "espanyol": "Espanol", "rayo vallecano": "Vallecano", "alaves": "Alaves", "deportivo alaves": "Alaves",
    "real madrid": "Real Madrid", "barcelona": "Barcelona", "sevilla": "Sevilla", "valencia": "Valencia",
    "villarreal": "Villarreal", "girona": "Girona", "osasuna": "Osasuna", "mallorca": "Mallorca",
    "real oviedo": "Oviedo", "oviedo": "Oviedo", "real valladolid": "Valladolid", "sporting gijon": "Sp Gijon",
    "gijon": "Sp Gijon", "racing santander": "Santander", "real zaragoza": "Zaragoza", "deportivo la coruna": "La Coruna",
    "la coruna": "La Coruna", "almeria": "Almeria", "las palmas": "Las Palmas", "leganes": "Leganes",
    "paris saint germain": "Paris SG", "paris": "Paris SG", "psg": "Paris SG", "saint etienne": "St Etienne",
    "olympique marseille": "Marseille", "olympique de marseille": "Marseille", "olympique lyonnais": "Lyon",
    "lyon": "Lyon", "lille": "Lille", "monaco": "Monaco", "nice": "Nice", "rennais": "Rennes",
    "stade rennais": "Rennes", "brest": "Brest", "stade brestois": "Brest", "lens": "Lens", "racing lens": "Lens",
    "strasbourg": "Strasbourg", "strasbourg alsace": "Strasbourg", "nantes": "Nantes", "toulouse": "Toulouse",
    "le havre": "Le Havre", "auxerre": "Auxerre", "angers": "Angers", "lorient": "Lorient", "metz": "Metz",
    "paris fc": "Paris FC",
    "psv": "PSV Eindhoven", "psv eindhoven": "PSV Eindhoven", "ajax": "Ajax", "feyenoord": "Feyenoord",
    "az": "AZ Alkmaar", "az alkmaar": "AZ Alkmaar", "twente": "Twente", "utrecht": "Utrecht",
    "go ahead eagles": "Go Ahead Eagles", "nec": "Nijmegen", "nec nijmegen": "Nijmegen", "heerenveen": "Heerenveen",
    "sparta rotterdam": "Sparta Rotterdam", "fortuna sittard": "For Sittard", "pec zwolle": "Zwolle",
    "zwolle": "Zwolle", "groningen": "Groningen", "willem ii": "Willem II", "nac breda": "NAC Breda",
    "heracles": "Heracles", "heracles almelo": "Heracles", "excelsior": "Excelsior", "telstar": "Telstar",
    "benfica": "Benfica", "lisboa benfica": "Benfica", "porto": "Porto", "portugal": "Sp Lisbon",
    "sporting cp": "Sp Lisbon", "sporting lisbon": "Sp Lisbon", "sporting clube portugal": "Sp Lisbon",
    "braga": "Sp Braga", "sporting braga": "Sp Braga", "vitoria guimaraes": "Guimaraes", "guimaraes": "Guimaraes",
    "galatasaray": "Galatasaray", "fenerbahce": "Fenerbahce", "besiktas": "Besiktas", "trabzonspor": "Trabzonspor",
    "istanbul basaksehir": "Buyuksehyr", "basaksehir": "Buyuksehyr",
    "real racing club": "Santander", "racing santander": "Santander", "racing club": "Santander",
    "rc deportivo a coruna": "La Coruna", "deportivo a coruna": "La Coruna", "deportivo la coruna": "La Coruna",
    "kuopion palloseura": "KuPS", "ca mineiro": "Atletico-MG", "atletico mineiro": "Atletico-MG",
    "ca paranaense": "Athletico-PR", "athletico paranaense": "Athletico-PR", "amed sportif": "Amedspor",
    "rams basaksehir": "Buyuksehyr", "istanbul basaksehir": "Buyuksehyr", "basaksehir": "Buyuksehyr",
    "austria lustenau": "A. Lustenau", "st truidense": "St Truiden", "st truidense vv": "St Truiden", "sint truidense": "St Truiden",
    "heart of midlothian": "Hearts", "rayo vallecano de madrid": "Vallecano", "celta fortuna": "Celta B",
    "celtic": "Celtic", "rangers": "Rangers", "heart midlothian": "Hearts", "hearts": "Hearts",
    "hibernian": "Hibernian", "aberdeen": "Aberdeen", "dundee united": "Dundee United", "st mirren": "St Mirren",
    "club brugge": "Club Brugge", "brugge": "Club Brugge", "anderlecht": "Anderlecht", "genk": "Genk",
    "union saint gilloise": "St. Gilloise", "saint gilloise": "St. Gilloise", "union sg": "St. Gilloise",
    "gent": "Gent", "standard liege": "Standard", "antwerp": "Antwerp",
    "olympiakos": "Olympiakos", "olympiacos": "Olympiakos", "olympiakos sfp": "Olympiakos", "paok": "PAOK",
    "aek athens": "AEK", "aek": "AEK", "panathinaikos": "Panathinaikos",
    "red bull salzburg": "Salzburg", "salzburg": "Salzburg", "sturm graz": "Sturm Graz", "rapid wien": "Rapid Vienna",
    "kobenhavn": "FC Copenhagen", "copenhagen": "FC Copenhagen", "midtjylland": "Midtjylland",
    "bodo glimt": "Bodo/Glimt", "bodo/glimt": "Bodo/Glimt", "molde": "Molde",
    "malmo": "Malmo FF", "malmo ff": "Malmo FF", "young boys": "Young Boys", "basel": "Basel",
    "bor monchengladbach": "M'gladbach", "lazio roma": "Lazio", "brestois 29": "Brest",
    "stade brestois 29": "Brest", "qarabag agdam": "Qarabag", "shakhtar donetsk": "Shakhtar",
    "flamengo": "Flamengo RJ", "atletico mineiro": "Atletico-MG", "athletico paranaense": "Athletico-PR",
    "palmeiras": "Palmeiras", "corinthians": "Corinthians", "gremio": "Gremio", "internacional": "Internacional",
}


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def normalise(name: str) -> str:
    s = strip_accents(name).lower().replace("ø", "o").replace("æ", "ae").replace("ß", "ss")
    s = re.sub(r"[\.'’`]", "", s)
    s = re.sub(r"[^a-z0-9/& ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def core_tokens(name: str) -> str:
    toks = [t for t in normalise(name).split() if t not in STOP]
    return " ".join(toks)


@dataclass
class TeamMatch:
    source_name: str
    canonical: str | None
    method: str
    score: float


_RESERVE_TOKENS = {"b", "ii", "u23", "u21", "u19", "reserves", "jong", "atletic", "promesas"}


def is_reserve(name: str) -> bool:
    return bool(set(normalise(name).split()) & _RESERVE_TOKENS)


def match_team(name: str, candidates: list[str], threshold: float = 0.84) -> TeamMatch:
    """Resolve ``name`` to one of ``candidates`` (canonical football-data names).

    Reserve/B sides only ever match reserve sides (and vice versa) in the
    approximate stages, so "Celta Fortuna" can never silently become "Celta".
    """
    if not candidates:
        return TeamMatch(name, None, "no-candidates", 0.0)
    cand_set = set(candidates)
    if name in cand_set:
        return TeamMatch(name, name, "exact", 1.0)
    n, c = normalise(name), core_tokens(name)
    norm_map = {normalise(x): x for x in candidates}
    core_map: dict[str, list[str]] = {}
    for x in candidates:
        core_map.setdefault(core_tokens(x), []).append(x)
    for key in (n, c):
        if key in ALIASES and ALIASES[key] in cand_set:
            return TeamMatch(name, ALIASES[key], "alias", 1.0)
    if n in norm_map:
        return TeamMatch(name, norm_map[n], "normalised", 1.0)
    if c and c in core_map and len(core_map[c]) == 1:
        return TeamMatch(name, core_map[c][0], "core-tokens", 0.97)
    res = is_reserve(name)
    candidates = [x for x in candidates if is_reserve(x) == res]
    # token containment, unique
    ctoks = set(c.split())
    if ctoks:
        hits = [x for x in candidates if (core_tokens(x) and set(core_tokens(x).split()) <= ctoks)
                or (set(core_tokens(x).split()) >= ctoks and len(ctoks) >= 1 and len(c) >= 5)]
        if len(hits) == 1:
            return TeamMatch(name, hits[0], "token-subset", 0.9)
    best, best_s = None, 0.0
    for x in candidates:
        s = max(difflib.SequenceMatcher(None, c, core_tokens(x)).ratio(),
                difflib.SequenceMatcher(None, n, normalise(x)).ratio())
        if s > best_s:
            best, best_s = x, s
    if best_s >= threshold:
        return TeamMatch(name, best, "fuzzy", round(best_s, 3))
    return TeamMatch(name, None, "unmatched", round(best_s, 3))


def team_key(country: str, name: str) -> str:
    return f"{country}:{name}"
