"""Owner policy: men's competitions only, enforced before fitting and publication."""
import re
from . import config
WOMEN=re.compile(r"women|female|femeni|femini|frauen|kvinner|vrouwen",re.I)
def allowed(subcategory='',competition=''):
    return str(subcategory).lower() in config.JUPITER_SUBCATEGORY_DIVS and not WOMEN.search(str(competition))
def fixture_allowed(fixture):
    return allowed(fixture.get('subcategory',''),fixture.get('competition','')) and not WOMEN.search(str(fixture.get('home_name',fixture.get('home','')))+' '+str(fixture.get('away_name',fixture.get('away',''))))
