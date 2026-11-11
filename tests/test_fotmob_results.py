from datetime import date
import pytest
from oraclefc.ingest.fotmob_results import parse_results

def body():return {'details':{'id':9125,'gender':'male','selectedSeason':'2026'},'fixtures':{'allMatches':[{'home':{'id':1,'name':'Real Cundinamarca'},'away':{'id':2,'name':'Real Cartagena'},'odds':{'x':1},'status':{'utcTime':'2026-10-01T18:00:00Z','finished':True,'scoreStr':'2 - 1','reason':{'shortKey':'fulltime_short'}}}]}}
def rows(b):return list(parse_results(b,'COL2',9125,'2026','source',today=date(2026,11,11)))
def test_verified_men_regulation_results_only():
    r=rows(body())[0];assert (r['home_key'],r['hg'],r['ag'])==('Colombia:fotmob-1',2,1);assert 'odds' not in r
@pytest.mark.parametrize('key,value',[('id',42),('gender','female'),('gender',None),('selectedSeason','2025')])
def test_wrong_identity_gender_and_season_rejected(key,value):
    b=body();b['details'][key]=value;assert not rows(b)
@pytest.mark.parametrize('key,value',[('finished',False),('awarded',True),('cancelled',True),('scoreStr','2 - 1 (pens)'),('utcTime','2026-11-11T10:00:00Z')])
def test_non_results_never_train(key,value):
    b=body();b['fixtures']['allMatches'][0]['status'][key]=value;assert not rows(b)
def test_no_extra_time_scores():
    b=body();b['fixtures']['allMatches'][0]['status']['reason']['shortKey']='after_extra_time_short';assert not rows(b)
