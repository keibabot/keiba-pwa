"""NAR pre-race-only model; October is an already-inspected retrospective period.
No final popularity, final odds, finish, time or payout enters features.
CLI: python trio_model.py. Inference: predict_entries(bundle, horses, race).
"""
import csv,io,zipfile,re,json,math,pickle,hashlib
from pathlib import Path
from collections import defaultdict
from itertools import combinations
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import brier_score_loss,roc_auc_score
from research.domain import allowlisted, SCHEMA
ROOT=Path(__file__).resolve().parent
OUT=ROOT/'model_data'
EXCLUDE={'門別','帯広ば'}
RECORDS=['全成績','当競馬場成績','うち当距離成績','ダート左成績','ダート右成績','騎手成績']

def num(v):
 m=re.search(r'[-+]?\d+(?:\.\d+)?',str(v or '').replace(',',''))
 return float(m.group()) if m else float('nan')
def record(v):
 a=re.findall(r'\d+',str(v or ''))
 if len(a)!=4:return [float('nan')]*4
 w,s,t,o=map(int,a);n=w+s+t+o
 return [math.log1p(n),(w+1)/(n+5),(w+s+t+3)/(n+10),float(n==0)]
def key(r):return (r['競走年月日'],r['競馬場'],r['レース番号'])
def read_zip(path):
 with zipfile.ZipFile(path) as z:
  return {kind:list(csv.DictReader(io.StringIO(z.read(next(n for n in z.namelist() if n.endswith('_'+kind+'.csv'))).decode('utf-8-sig')))) for kind in ['horselist','racelist','payback']}
def features(horses,race):
 horses,race=allowlisted(horses,race)
 rows=[]
 for h in horses:
  a=[num(h.get(k)) for k in ['齢','負担重量','馬体重','馬体重増減','枠番','馬番']]
  a += [num(race.get('距離')),len(horses),float(h.get('性')=='牝'),float(h.get('性') in ['セン','セ']),float(race.get('回り')=='左')]
  for k in RECORDS:a+=record(h.get(k))
  rows.append(a)
 X=np.array(rows,dtype=float)
 # Race-relative standing is computable at prediction time from all runners.
 rel=[]
 for j in [0,1,2,3,13,17,21,33]:
  v=X[:,j];finite=v[np.isfinite(v)]; mean=float(finite.mean()) if len(finite) else 0
  rel.append(v-mean)
 return np.column_stack([X,*rel])
def prepare(path):
 data=read_zip(path); races={key(r):r for r in data['racelist']};pay=defaultdict(list);groups=defaultdict(list)
 for p in data['payback']:pay[key(p)].append(p)
 for h in data['horselist']:
  if h['競馬場'] not in EXCLUDE and h.get('着順') not in ['取消','除外']:groups[key(h)].append(h)
 result=[];skipped=defaultdict(int)
 for k,hs in sorted(groups.items(),key=lambda item:(item[0][0],races.get(item[0],{}).get('発走時刻','9999'),item[0][1],int(item[0][2]))):
  if len(hs)<5 or k not in races:skipped['small_or_missing_race']+=1;continue
  # Need complete finish labels, allowing nonfinishers but not blank results.
  if any(not h.get('着順','').strip() for h in hs):skipped['unfinished']+=1;continue
  winners=[]
  for p in pay[k]:
   vals=[num(p.get('３連複組番馬番'+str(i))) for i in (1,2,3)]
   amount=num(p.get('３連複払戻金（円）'))
   if all(np.isfinite(vals)) and np.isfinite(amount) and amount>0:
    winners.append((tuple(sorted(int(v) for v in vals)),amount))
  if not winners:skipped['missing_trio_payback']+=1;continue
  # Refuse malformed duplicate horse numbers or payouts.
  if len({h['馬番'] for h in hs})!=len(hs):skipped['duplicate_horse']+=1;continue
  result.append({'key':k,'horses':hs,'race':races[k],'X':features(hs,races[k]),'y':np.array([int(np.isfinite(num(h['着順'])) and 1<=num(h['着順'])<=3) for h in hs]),'winners':list(dict.fromkeys(winners))})
 return result,dict(skipped)
def picks(numbers,scores,kind):
 order=[numbers[i] for i in sorted(range(len(numbers)),key=lambda i:(-scores[i],numbers[i]))]
 if kind=='axis6':return [tuple(sorted((order[0],*c))) for c in combinations(order[1:5],2)]
 return [tuple(sorted(c)) for c in combinations(order[:5],3)]
def summarize(rows):
 n=len(rows);stake=sum(r['stake'] for r in rows);payout=sum(r['payout'] for r in rows);hits=sum(r['hit'] for r in rows)
 high=sum(r['hit'] and r['winning_payback_100']>=10000 for r in rows)
 balance=peak=draw=run=longest=0
 for r in rows:
  balance+=r['payout']-r['stake'];peak=max(peak,balance);draw=max(draw,peak-balance)
  run=0 if r['hit'] else run+1;longest=max(longest,run)
 p=hits/n if n else 0;z=1.96;den=1+z*z/n if n else 1
 center=(p+z*z/(2*n))/den if n else 0;half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den if n else 0
 return {'races':n,'hits':hits,'hit_rate':p,'hit_rate_wilson95':[max(0,center-half),min(1,center+half)],'stake':stake,'payout':payout,'profit':payout-stake,'roi_pct':payout/stake*100 if stake else None,'high_payout_hits':high,'max_drawdown':draw,'max_losing_streak':longest}
def evaluate(model,groups,kind):
 rows=[]
 for g in groups:
  scores=model.predict_proba(g['X'])[:,1] if model is not None else g['X'][:,13]
  scores=np.nan_to_num(scores,nan=-1)
  tickets=picks([int(h['馬番']) for h in g['horses']],scores,kind);unit=500 if kind=='axis6' else 300
  matches=[p for t,p in g['winners'] if t in tickets];payout=sum(matches)*unit/100
  rows.append({'date':g['key'][0],'track':g['key'][1],'race':g['key'][2],'tickets':tickets,'unit':unit,'stake':unit*len(tickets),'payout':payout,'hit':bool(matches),'winning_payback_100':max(matches,default=0)})
 tracks={t:summarize([r for r in rows if r['track']==t]) for t in sorted({r['track'] for r in rows})}
 return {'overall':summarize(rows),'by_track':tracks},rows

def predict_entries(bundle,horses,race):
 if race.get('競馬場') in EXCLUDE:return {'status':'excluded','horses':[],'tickets':[]}
 if len(horses)<5:return {'status':'insufficient_runners','horses':[],'tickets':[]}
 scores=bundle['model'].predict_proba(features(horses,race))[:,1]
 ranked=sorted([{'number':int(h['馬番']),'name':h['馬名'],'model_score':float(p)} for h,p in zip(horses,scores)],key=lambda x:(-x['model_score'],x['number']))
 return {'status':'research_only','model_version':bundle['version'],'horses':ranked,'tickets':picks([int(h['馬番']) for h in horses],scores,bundle['strategy']),'calibrated_probability':False,'warning':'研究用スコア。三連複的中確率ではありません。回収率優位性は未確認。'}

def main():
 OUT.mkdir(exist_ok=True)
 train=[];counts={};sources=[]
 for month in [7,8,9,10]:
  path=(ROOT/'nar_202610.zip') if month==10 else OUT/f'nar_2026{month:02}.zip'
  groups,skip=prepare(path);counts[str(month)]={'races':len(groups),'horses':sum(len(g['y']) for g in groups),'skipped':skip}
  sources.append({'month':month,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'url':f'https://www.keiba.go.jp/KeibaWeb/DataDownload/RaceDataDownload?k_month={month}&k_year=2026&type=monthly'})
  if month<9:train+=groups
  elif month==9:valid=groups
  else:test=groups
 X=np.concatenate([g['X'] for g in train]);y=np.concatenate([g['y'] for g in train]);VX=np.concatenate([g['X'] for g in valid]);vy=np.concatenate([g['y'] for g in valid])
 candidates={'logistic':make_pipeline(SimpleImputer(add_indicator=True),StandardScaler(),LogisticRegression(max_iter=1000,C=0.3)), 'hist_gradient':HistGradientBoostingClassifier(max_iter=150,max_leaf_nodes=15,min_samples_leaf=80,l2_regularization=10,learning_rate=.06,random_state=42)}
 validation={}
 for name,m in candidates.items():
  m.fit(X,y);p=m.predict_proba(VX)[:,1]
  validation[name]={'brier':brier_score_loss(vy,p),'auc':roc_auc_score(vy,p),'strategies':{kind:evaluate(m,valid,kind)[0] for kind in ['axis6','box10']}}
 selected=min(validation,key=lambda name:validation[name]['brier'])
 # September selects the score model. October was already inspected; never retune on it and call it untouched.
 m=candidates[selected];summary={'version':'trio-pre-race-v1','counts':counts,'sources':sources,'training':'2026-07-01..2026-08-31','selection':'2026-09-01..2026-09-30 Brier score','holdout':'2026-10-01..2026-10-31','excluded_tracks':sorted(EXCLUDE),'budget_each_race':3000,'validation':validation,'selected_model':selected,'holdout_results':{},'limitations':['Retrospective replay using official pre-race cumulative fields; not a prospective live trial.','Final popularity and odds excluded from model inputs. No value/EV claim.','October inspected once after model selection; later changes require a new untouched period.','No horse ID; this version uses provided cumulative fields, not name-joined histories.','Cancelled/excluded runners removed retrospectively; DNF retained as losses.','No profitability claim from individual track maxima.','All score models uncalibrated; probabilities are ranking scores, not ticket probabilities.']}
 allrows={}
 for name,model in [(selected,m),('historical_top3_baseline',None)]:
  for kind in ['axis6','box10']:
   label=name+'_'+kind;summary['holdout_results'][label],allrows[label]=evaluate(model,test,kind)
 summary['evaluation_status']='October already inspected; retrospective comparison, not an unused final test'
 summary['feature_schema']=SCHEMA
 bundle={'model':m,'strategy':'axis6','version':summary['version'],'feature_schema':SCHEMA,'features':'whitelisted pre-race numeric cumulative fields','trained_until':'20260831'}
 with (OUT/'trio_model.pkl').open('wb') as f:pickle.dump(bundle,f)
 (OUT/'model_report.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
 (OUT/'holdout_tickets.json').write_text(json.dumps(allrows,ensure_ascii=False),encoding='utf-8')
 print(json.dumps({'counts':counts,'selected':selected,'validation_brier':{n:v['brier'] for n,v in validation.items()},'holdout':{k:v['overall'] for k,v in summary['holdout_results'].items()}},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
