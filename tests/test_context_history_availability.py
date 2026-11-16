import pandas as pd
from oraclefc import config
from oraclefc.context import history as H

def fixture():
 return pd.DataFrame({'match_id':['winter','summer','unknown','invalid'],'date':pd.to_datetime(['2026-11-15','2026-07-15','2026-11-15','2026-11-15']),'home_key':['H']*4,'away_key':['A']*4,'kickoff':['15:00','15:00',None,'25:99']})

def test_optional_fixture_file_missing_uses_known_uk_kickoff_only(tmp_path,monkeypatch):
 monkeypatch.setattr(config,'CLEAN_DIR',tmp_path)
 out=H.kickoff_utc(fixture())
 assert out.iloc[0]==pd.Timestamp('2026-11-15T15:00')
 assert out.iloc[1]==pd.Timestamp('2026-07-15T14:00')
 assert out.iloc[2:].isna().all(),'unknown times must not become fabricated weather observations'

def test_mapped_utc_fixture_retained_over_fallback(tmp_path,monkeypatch):
 monkeypatch.setattr(config,'CLEAN_DIR',tmp_path)
 pd.DataFrame({'home_key':['H'],'away_key':['A'],'utc':['2026-11-15T18:30Z']}).to_parquet(tmp_path/'fotmob_fixtures.parquet')
 out=H.kickoff_utc(fixture().iloc[:1]);assert out.iloc[0]==pd.Timestamp('2026-11-15T18:30')

def test_no_weather_coverage_has_stable_merge_schema(monkeypatch):
 called=[];monkeypatch.setattr(H,'power_cell',lambda *a:called.append(a))
 f=fixture();f['ko_utc']=pd.NaT;f['venue_lat']=1.;f['venue_lon']=1.
 weather=H.weather_table(f)
 assert not called and weather.empty
 merged=f.merge(weather,on='match_id',how='left');assert merged['temp_c'].isna().all()

def test_context_feature_builder_survives_missing_fixture_file(tmp_path,monkeypatch):
 from oraclefc.run_context_backtest import features
 monkeypatch.setattr(config,'CLEAN_DIR',tmp_path)
 f=fixture().iloc[:1].copy();f['kickoff']=None;f['div']='E0';f['neutral']=False
 venues=pd.DataFrame({'team_key':['H','A'],'lat':[51.,52.],'lon':[0.,1.]}).set_index('team_key')
 monkeypatch.setattr(H,'venues',lambda:venues)
 monkeypatch.setattr(H,'power_cell',lambda *args:(_ for _ in ()).throw(AssertionError('unknown kickoff must not fetch weather')))
 lu=pd.DataFrame({'us_id':[1],'match_id':['winter'],'A_h':[0.],'A_a':[0.],'C_h':[0.],'C_a':[0.],'G_h':[0.],'G_a':[0.]})
 monkeypatch.setattr(H,'lineup_history',lambda _: (lu,None))
 out=features(f,pd.DataFrame())
 assert len(out)==1 and pd.isna(out.iloc[0]['temp_c']) and pd.isna(out.iloc[0]['ko_utc'])
 assert out.iloc[0]['A_h']==0 and out.iloc[0]['travel_km']>0
