"""Men's results only, source-qualified IDs and regulation full-time score allowlist."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import hashlib,json,re
import pandas as pd
from .. import config
from ..governance import Provenance,now_utc_iso
from .http import get_json
BASE='https://www.fotmob.com/api/data/leagues'
def parse_results(body,div,lid,season,url,*,today=None):
    d=body.get('details',{})
    if str(d.get('id'))!=str(lid) or d.get('gender')!='male' or d.get('selectedSeason')!=season:return
    today=today or datetime.now(timezone.utc).date();country=config.SUPPLEMENTAL_DIVISIONS[div][0]
    for m in (body.get('fixtures') or {}).get('allMatches',[]):
        s=m.get('status') or {};reason=s.get('reason') or {}
        if s.get('finished') is not True or s.get('cancelled') or s.get('awarded') or reason.get('shortKey')!='fulltime_short':continue
        score=re.fullmatch(r'(\d+)\s*-\s*(\d+)',str(s.get('scoreStr','')))
        if not score:continue
        try:
            dt=datetime.fromisoformat(s['utcTime'].replace('Z','+00:00'));h,a=m['home'],m['away']
            if dt.tzinfo is None or dt.date()>=today or not h['id'] or not a['id'] or str(h['id'])==str(a['id']) or not h['name'] or not a['name']:continue
        except (KeyError,TypeError,ValueError):continue
        yield dict(date=pd.Timestamp(dt.date()),kickoff=dt.strftime('%H:%M'),div=div,country=country,season=season,
                   home=h['name'],away=a['name'],home_key=f"{country}:fotmob-{h['id']}",away_key=f"{country}:fotmob-{a['id']}",
                   hg=int(score[1]),ag=int(score[2]),neutral=bool(m.get('neutralVenue',False)),source='fotmob',source_file=url)
def _league(task):
    div,lid=task;raw=config.RAW_DIR/'fotmob-results'
    def get(season=None):
        path=raw/f'{lid}-{(season or "current").replace("/","-")}.json'
        b=get_json(BASE,path,max_age_h=168 if season else 6,params={'id':lid,**({'season':season} if season else {})},timeout=10,retries=1)
        return b if b is not None or not path.exists() else get_json(BASE,path)
    b=get()
    if not isinstance(b,dict):return [],[]
    year=datetime.now(timezone.utc).year;rows=[];ps=[]
    for season in b.get('allAvailableSeasons',[]):
        if not re.fullmatch(r'\d{4}(?:/\d{4})?',season) or not year-2<=int(season[:4])<=year:continue
        data=b if b.get('details',{}).get('selectedSeason')==season else get(season)
        if not isinstance(data,dict):continue
        url=f'{BASE}?id={lid}&season={season}';r=list(parse_results(data,div,lid,season,url))
        if r:
            rows+=r;ps.append(Provenance('fotmob',url,now_utc_iso(),len(r),['verified male league','kickoff','team identity','regulation score'],sha256=hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()).to_dict())
    return rows,ps
def fetch():
    with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(_league,config.FOTMOB_RESULT_FEEDS.items()))
    return pd.DataFrame([r for rows,_ in results for r in rows]),[p for _,ps in results for p in ps]
