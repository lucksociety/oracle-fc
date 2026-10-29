"""Reconcile unresolved frozen dates and recheck recent corrections; never rewrite predictions."""
import json,sys
from pathlib import Path
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from oraclefc.market import grade

def pending_dates(root,today):
    dates=[]
    for p in sorted((root/'data/forecasts').iterdir()):
        if not p.is_dir():continue
        try:day=datetime.fromisoformat(p.name).date()
        except ValueError:continue
        if day>=today:continue
        result=root/'data/results'/f'{p.name}.json'
        rows=json.loads(result.read_text()).get('games',[]) if result.exists() else []
        if day>=today-timedelta(days=7) or not rows or any(g.get('status')!='final' for g in rows):dates.append(p.name)
    return dates

def main():
    for date in pending_dates(ROOT,datetime.now(ZoneInfo('America/New_York')).date()):grade.write(date,grade.grade_date(date))

if __name__=='__main__':main()
