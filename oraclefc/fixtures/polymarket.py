"""Full-day men-only Polymarket fixture inventory, independent of model coverage.

Only allowlisted identities and scheduled kickoff enter the clean cache/engine.
Settlement/status/score fields can conflict and are deliberately not used here.
"""
from __future__ import annotations
import json
import re
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import requests
from .. import config
from ..governance import now_utc_iso
from ..sports_policy import fixture_allowed, WOMEN, WOMEN_COMPETITIONS
from .jupiter import Fixture, TITLE_RE

BASE='https://gamma-api.polymarket.com/events'
CACHE_DIR=config.DATA_DIR/'cache'/'polymarket-fixtures'
PAGE_SIZE=100
MAX_PAGES=100
PARENT=re.compile(r'^(?P<code>[a-z0-9]+)-[a-z0-9]+-[a-z0-9]+-\d{4}-\d{2}-\d{2}$')

def _get(params):
    for attempt in range(3):
        try:
            response=requests.get(BASE,params=params,headers={'User-Agent':'oracle-fc/1.0 (fixture identities only)'},timeout=15)
            response.raise_for_status()
            data=response.json()
            if not isinstance(data,list):raise requests.RequestException('Polymarket fixture page is not an array')
            return data
        except requests.RequestException as exc:
            status=getattr(getattr(exc,'response',None),'status_code',None)
            if attempt==2 or status is not None and status!=429 and status<500:raise
            time.sleep(2**attempt)

def sanitise_event(event,date,tz=config.USER_TZ):
    parent=PARENT.fullmatch(str(event.get('slug','')))
    title=TITLE_RE.fullmatch(str(event.get('title','')))
    eid=str(event.get('id',''))
    if not parent or not title or not eid.isdigit():return None
    tags=event.get('tags') or []
    if not any(t.get('slug')=='soccer' for t in tags):return None
    if any(WOMEN.search(str(t.get('label',''))+' '+str(t.get('slug',''))) or t.get('slug') in WOMEN_COMPETITIONS for t in tags):return None
    sport=event.get('sport') or {}
    code=parent['code']
    if sport.get('sport') and sport['sport']!=code:return None
    competition=str(sport.get('name') or code)
    identity=dict(subcategory=code,competition=competition,home_name=title['h'].strip(),away_name=title['a'].strip())
    if not fixture_allowed(identity):return None
    # startTime is scheduled kickoff. The date embedded in a slug may be stale after rescheduling.
    try:
        kickoff=datetime.fromisoformat(str(event['startTime']).replace('Z','+00:00'))
        if kickoff.tzinfo is None or str(kickoff.astimezone(ZoneInfo(tz)).date())!=date:return None
    except (KeyError,ValueError,TypeError):return None
    return Fixture(event_id='POLY-'+eid,**identity,kickoff_utc=kickoff.astimezone(timezone.utc).isoformat(),
                   slug=event['slug'],source='polymarket-fixtures')

def fixtures_for_date(date,tz=config.USER_TZ,use_cache=True):
    start=datetime.fromisoformat(date).replace(tzinfo=ZoneInfo(tz))
    end=start+timedelta(days=1)
    cache=CACHE_DIR/f'{date}-{tz.replace("/","_")}.json'
    if use_cache and cache.exists() and time.time()-cache.stat().st_mtime<600:
        try:
            body=json.loads(cache.read_text())
            if body.get('policy')=='full-day-men-v1' and body.get('complete') is True:
                return [Fixture(**f) for f in body['fixtures'] if fixture_allowed(f)]
        except (ValueError,TypeError,KeyError,OSError):pass
    found={}
    # Query both states explicitly. Live, completed and pregame games belong to the same daily inventory.
    for closed in ('false','true'):
        for page in range(MAX_PAGES):
            data=_get(dict(tag_id='100350',start_time_min=start.astimezone(timezone.utc).isoformat(),
                           start_time_max=end.astimezone(timezone.utc).isoformat(),closed=closed,
                           limit=PAGE_SIZE,offset=page*PAGE_SIZE,order='id',ascending='true'))
            for event in data:
                fixture=sanitise_event(event,date,tz)
                if fixture:found[fixture.event_id]=fixture
            if len(data)<PAGE_SIZE:break
        else:raise requests.RequestException('Polymarket fixture pagination safety limit reached; refusing partial inventory')
    fixtures=sorted(found.values(),key=lambda f:(f.kickoff_utc,f.competition,f.home_name))
    cache.parent.mkdir(parents=True,exist_ok=True)
    cache.write_text(json.dumps(dict(policy='full-day-men-v1',date=date,tz=tz,complete=True,fetched_at=now_utc_iso(),fixtures=[f.to_dict() for f in fixtures])))
    return fixtures
