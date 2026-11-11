"""Owner policy: men's competitions only, enforced before fitting and publication."""
import re
from . import config
WOMEN=re.compile(r"women|female|femeni|femini|frauen|kvinner|vrouwen",re.I)
# Reviewed against Polymarket's soccer competition registry, 2026-11-11.
# Discovery coverage is independent of which competitions the model can rate.
MEN_COMPETITIONS = frozenset(['acl2', 'acle', 'afc', 'afcl', 'afcq', 'afwq', 'arg', 'argcopa', 'argpn', 'asean', 'aseanc', 'aswq', 'atc',
 'auc', 'aus', 'aut', 'aze1', 'aze2', 'azec', 'bel1', 'bel2', 'bl2', 'bl3', 'blr1', 'bol1', 'bra', 'bra2',
 'bra3', 'brcm', 'brco', 'bul', 'bun', 'caf', 'cafcl', 'canch', 'canpl', 'ccc', 'ccup', 'cde', 'cdr', 'chfa',
 'chi', 'chi1', 'chi2', 'chl2', 'clf', 'cof', 'col', 'col1', 'col2', 'con', 'conl', 'copaam', 'cwc', 'cze1',
 'den', 'dfb', 'ecs', 'ecu1', 'efa', 'efl', 'egy1', 'el1', 'el2', 'elc', 'enl', 'epl', 'ere', 'es2', 'es3',
 'est1', 'euc', 'ewq', 'fif', 'fifwc', 'fin1', 'fl1', 'fpd', 'fr2', 'fro1', 'frtc', 'geo1', 'grc', 'gre1',
 'gsc', 'gtm', 'hr1', 'hun', 'icwq', 'idn1', 'idn2', 'ire', 'irl1', 'isc', 'isl1', 'isp', 'isr', 'itc',
 'itsb', 'j1100', 'j2100', 'ja2', 'ja3', 'jap', 'kaz1', 'kor', 'kor2', 'lal', 'lec', 'lib', 'ltu1', 'lva1',
 'mar1', 'mex', 'mex2', 'mls', 'nawq', 'ncag', 'ned2', 'nirl1', 'nlc', 'nln', 'nls', 'nor', 'nor2', 'ofc',
 'owq', 'par1', 'per1', 'pol', 'por', 'pt2', 'ptc', 'ptsc', 'qat1', 'rou1', 'rus', 'saf1', 'sawq', 'sclc',
 'scoc', 'scop', 'sea', 'serc', 'skc', 'slo', 'spl', 'srb', 'ssc', 'sud', 'sui', 'svk1', 'swe', 'swe2',
 'tha1', 'tpe1', 'trsk', 'tur', 'tur2', 'uae1', 'ucl', 'uef', 'uel', 'ueq', 'ukr1', 'unl', 'uru1', 'usc',
 'usl1', 'uslc', 'usoc', 'uzb1', 'ven1'])
WOMEN_COMPETITIONS = frozenset(['aseanw', 'fifaw', 'nwsl', 'tpew', 'u20wwc', 'uwcl', 'uwec', 'weuc', 'weuq', 'wsl', 'wsl2', 'wwcquefa'])
def allowed(subcategory='',competition=''):
    code=str(subcategory).lower()
    return code not in WOMEN_COMPETITIONS and (code in MEN_COMPETITIONS or code in config.JUPITER_SUBCATEGORY_DIVS) and not WOMEN.search(str(competition))
def fixture_allowed(fixture):
    return allowed(fixture.get('subcategory',''),fixture.get('competition','')) and not WOMEN.search(str(fixture.get('home_name',fixture.get('home','')))+' '+str(fixture.get('away_name',fixture.get('away',''))))
