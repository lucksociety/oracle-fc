"""Chronological, results-only supplemental-league validation.

Temperatures are selected on 2025 only; adoption is evaluated on 2026 heldout
weekly forecasts. Excludes the previous calendar day from training because
historical rows do not establish exact final-score availability. No prices.
Run from any directory; see research/supplemental-validation.md.
"""
import sys,json,datetime as dt,time,hashlib
from pathlib import Path
import numpy as np,pandas as pd
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
from oraclefc.models.dixon_coles import dynamic_dc
from oraclefc.simulate import summarise
import argparse
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--data', type=Path, required=True)
parser.add_argument('--through', default='2026-11-10')
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--oos-cache', type=Path, required=True)
args=parser.parse_args()
through=pd.Timestamp(args.through).normalize()
if through.year!=2026:parser.error("This policy version uses 2025 tuning and 2026 heldout results")
end=through+pd.Timedelta(days=1)
df=pd.read_parquet(args.data)

D=['BRA2','COL2','MEX2','COL','CRC','D3','PAR','PER','VEN','RG'];df=df[df['div'].isin(D)].copy();df['date']=pd.to_datetime(df['date'])
params=json.loads((root/'experiments/registry.json').read_text())['champion']['params']
cache=args.oos_cache;rows=[];mats=[];prior=[]
for cutoff in pd.date_range('2024-12-30',through,freq='7D'):
 te=df[(df['date']>=cutoff)&(df['date']<min(cutoff+pd.Timedelta(days=7),end))]
 if te.empty:continue
 model=dynamic_dc(params['half_life_days'],params['kappa']);train=df[df['date']<cutoff-pd.Timedelta(days=1)];model.fit(train,cutoff)
 te=te[[model.n_matches_weighted.get(r.home_key,0)>=8 and model.n_matches_weighted.get(r.away_key,0)>=8 for r in te.itertuples()]]
 if te.empty:continue
 M=model.predict_matrix(te)
 for r,m in zip(te.to_dict('records'),M):
  if not np.isfinite(m).all():continue
  hist=train[(train['div']==r['div'])&(train['date']>=cutoff-pd.Timedelta(days=730))]
  if len(hist)<100:continue
  ps=np.array([(hist.hg>hist.ag).mean(),(hist.hg==hist.ag).mean(),(hist.hg<hist.ag).mean()]);ps=(ps*len(hist)+1)/(len(hist)+3)
  rows.append({k:str(r[k])if k in ['date','div','match_id']else int(r[k])for k in ['date','div','match_id','hg','ag']});mats.append(m);prior.append(ps)
 
 if cutoff.day<8:print(str(cutoff.date()),len(rows),flush=True)
np.savez_compressed(cache,M=np.array(mats),prior=np.array(prior),rows=np.array(json.dumps(rows)))
print('saved',len(rows),flush=True)

z=np.load(cache);rows=pd.DataFrame(json.loads(str(z['rows'])));M=z['M'];prior=z['prior'];h=np.arange(M.shape[1])[:,None];a=np.arange(M.shape[2])[None,:]
P=np.stack([M[:,h>a].sum(1),M[:,h==a].sum(1),M[:,h<a].sum(1)],axis=1);Y=np.stack([rows.hg>rows.ag,rows.hg==rows.ag,rows.hg<rows.ag],axis=1).astype(float)
actual=Y.argmax(1);log=lambda p:-np.log(np.maximum(1e-12,p[np.arange(len(p)),actual]));brier=lambda p:((p-Y)**2).sum(1)
def probs(p,t):
 q=p**(1/t);return q/q.sum(1,keepdims=True)
train=pd.to_datetime(rows.date).dt.year==2025;test=pd.to_datetime(rows.date).dt.year==2026;policy={};rng=np.random.default_rng(20261111)
for div in sorted(rows['div'].unique()):
 tr=(rows['div']==div)&train;te=(rows['div']==div)&test
 if tr.sum()<200 or te.sum()<200:print(div,'insufficient',tr.sum(),te.sum());continue
 T=min([1.,1.1,1.25,1.5],key=lambda t:log(probs(P,t))[tr].mean());Q=probs(P,T)
 dlog=log(Q)-log(prior);dbrier=brier(Q)-brier(prior)
 weeks=pd.to_datetime(rows.date).dt.to_period('W').astype(str);by=pd.DataFrame({'week':weeks[te],'ll':dlog[te],'bs':dbrier[te]}).groupby('week').agg(['sum','size'])
 ix=rng.integers(0,len(by),(4000,len(by)));vals={}
 for key in ['ll','bs']:
  sums=by[(key,'sum')].to_numpy();n=by[(key,'size')].to_numpy();boot=sums[ix].sum(1)/n[ix].sum(1);vals[key]=[float(x)for x in np.quantile(boot,[.005,.995])]
 joint0=-np.log(np.maximum(1e-12,M[np.arange(len(M)),rows.hg.clip(upper=M.shape[1]-1).to_numpy(int),rows.ag.clip(upper=M.shape[2]-1).to_numpy(int)]))
 result_ratio=Q[np.arange(len(Q)),actual]/np.maximum(1e-12,P[np.arange(len(P)),actual]);joint=joint0-np.log(np.maximum(1e-12,result_ratio))
 eligible=vals['ll'][1]<0 and vals['bs'][1]<0 and log(Q)[te].mean()<=log(P)[te].mean()+1e-12 and joint[te].mean()<=joint0[te].mean()+1e-12
 record={'eligible':bool(eligible),'temperature':T,'tune_n':int(tr.sum()),'test_n':int(te.sum()),'test_logloss':float(log(Q)[te].mean()),'baseline_logloss':float(log(prior)[te].mean()),'test_brier':float(brier(Q)[te].mean()),'baseline_brier':float(brier(prior)[te].mean()),'raw_model_logloss':float(log(P)[te].mean()),'exact_score_logloss':float(joint[te].mean()),'raw_exact_score_logloss':float(joint0[te].mean()),'baseline_delta_week_bootstrap_99':vals}
 policy[div]=record;print(div,record,flush=True)
params=json.loads((root/'experiments/registry.json').read_text())['champion']['params']
out={'schema':1,'policy':'supplemental-chronological-v1','model_params':params,'tune_year':2025,'test_window':['2026-01-01',str(through.date())],'result_through':str(through.date()),'data_source':'allowlisted men-only historical results','oos_input_sha256':hashlib.sha256(cache.read_bytes()).hexdigest(),'adoption':'At least 200 tuning and 200 heldout forecasts per league; candidate temperature selected only on 2025; 99% week-clustered CIs beat results-only league H/D/A prior on log loss and Brier; heldout 1X2 and exact-score loss no worse than uncalibrated model. No betting prices used; this does not establish profitable betting edge.','leagues':policy}
args.output.write_text(json.dumps(out,indent=2)+'\n')
