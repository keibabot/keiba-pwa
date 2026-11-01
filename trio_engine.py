"""Reproducible descriptive replay, not a prospective profitability estimate."""
import csv, io, json, re, zipfile, argparse, statistics
from collections import defaultdict
from itertools import combinations
from datetime import datetime, timezone

NAMES={'axis_1':'◉軸＋相手4頭・6点','axis_2':'◎軸＋相手4頭・6点','box_4':'上位4頭BOX・4点','box_5':'上位5頭BOX・10点','legacy_unordered':'旧買い目を三連複に変換'}
def combo(v):
    a=tuple(sorted(map(int,v)))
    if len(a)!=3 or len(set(a))!=3 or min(a)<1: raise ValueError('invalid triple')
    return a

def tickets(marks, old):
    ns=[int(m['number']) for m in marks]
    if len(ns)<5 or len(set(ns))!=len(ns): raise ValueError('need unique five marks')
    return {'axis_1':{combo([ns[0],*p]) for p in combinations(ns[1:5],2)},'axis_2':{combo([ns[1],*p]) for p in combinations([ns[0],*ns[2:5]],2)},'box_4':{combo(p) for p in combinations(ns[:4],3)},'box_5':{combo(p) for p in combinations(ns[:5],3)},'legacy_unordered':{combo(p) for p in re.findall(r'(\d+)-(\d+)-(\d+)',old)}}

def getmarks(row):
    return [{'label':m[0],'number':int(m[1]),'name':m[2].strip()} for m in re.findall(r'(◉|◎|▲|☆|△|\(\))\s*(\d+)\s+([^|]+)',row['memo'])]

def key(r,official=False):
    if official:return (r['競走年月日'],r['競馬場'].replace('帯広ば','帯広'),int(r['レース番号']))
    return (r['date'].replace('-',''),r['track'],int(re.sub(r'\D','',r['race'])))

def readzip(path,kind):
    with zipfile.ZipFile(path) as z:
        return list(csv.DictReader(io.StringIO(z.read(next(n for n in z.namelist() if n.endswith('_'+kind+'.csv'))).decode('utf-8-sig'))))

def pct(n,d): return round(100*n/d,2) if d else None

def analyze(zip_path,pred_path):
    pay=defaultdict(dict)
    for r in readzip(zip_path,'payback'):
        if r['競馬場']=='門別':continue
        try:
            c=combo([r['３連複組番馬番'+str(i)] for i in (1,2,3)])
            v=int(r['３連複払戻金（円）'])
            if v>0:pay[key(r,True)][c]=v
        except (ValueError,KeyError):pass
    hs=readzip(zip_path,'horselist'); horse_stats=defaultdict(lambda:[0,0]); horse_races=defaultdict(dict)
    for r in hs:
        if r['競馬場']=='門別':continue
        try:f=int(r['着順']);n=int(r['馬番'])
        except ValueError:continue
        if f<1:continue
        horse_stats[(r['馬名'],r['生年月日'])][0]+=1
        horse_stats[(r['馬名'],r['生年月日'])][1]+=f<=3
        horse_races[key(r,True)][n]=f
    predictions=list(csv.DictReader(open(pred_path,encoding='utf-8-sig')))
    unique={key(r):r for r in predictions if r['track']!='門別'}
    race_results=[]; mark_stats=defaultdict(lambda:[0,0]); skipped=0
    for k,r in sorted(unique.items()):
        if k not in pay:continue
        marks=getmarks(r)
        try:ts=tickets(marks,r['bet'])
        except ValueError:skipped+=1;continue
        # Cancelled/excluded participants: refund allocation is unavailable. Exclude entire race conservatively.
        if any(m['number'] not in horse_races[k] for m in marks):skipped+=1;continue
        strategies={sid:{'tickets':['-'.join(map(str,c)) for c in sorted(cs)],'hit':any(c in pay[k] for c in cs),'stake':100*len(cs),'payout':sum(pay[k].get(c,0) for c in cs)} for sid,cs in ts.items()}
        for m in marks:mark_stats[m['label']][0]+=1;mark_stats[m['label']][1]+=horse_races[k].get(m['number'],99)<=3
        race_results.append({'date':r['date'],'track':r['track'],'race':r['race'],'marks':marks,'finish_numbers':[n for n,f in sorted(horse_races[k].items(),key=lambda x:x[1]) if f<=3],'trio_payout':max(pay[k].values()),'strategies':strategies,'prediction_timing':'not_independently_verified'})
    def summary(sid,rows):
        vals=[r['strategies'][sid] for r in rows];stake=sum(v['stake'] for v in vals);payout=sum(v['payout'] for v in vals);hits=sum(v['hit'] for v in vals);balance=peak=dd=0
        for v in vals:balance+=v['payout']-v['stake'];peak=max(peak,balance);dd=max(dd,peak-balance)
        return {'id':sid,'name':NAMES[sid],'races':len(vals),'hits':hits,'hit_rate':pct(hits,len(vals)),'stake':stake,'payout':payout,'roi':pct(payout,stake),'high_payout_hits':sum(v['hit'] and r['trio_payout']>=10000 for v,r in zip(vals,rows)),'max_drawdown':dd}
    venues=[]
    for track in sorted({k[1] for k in pay}):
        vals=[max(v.values()) for k,v in pay.items() if k[1]==track];rows=[r for r in race_results if r['track']==track];s=summary('axis_2',rows)
        venues.append({'track':track,'races':len(vals),'median_trio_payout':statistics.median(vals),'high_payout_rate':pct(sum(v>=10000 for v in vals),len(vals)),'bot_races':len(rows),'bot_hit_rate':s['hit_rate'],'bot_roi':s['roi'],'bot_strategy':'axis_2'})
    return {'generated_at':datetime.now(timezone.utc).isoformat(),'source':{'url':'https://www.keiba.go.jp/','period':[min(k[0] for k in pay),max(k[0] for k in pay)],'official_races':len(pay),'predictions':len(unique),'matched_races':len(race_results),'skipped_races':skipped},'limitations':['保存済み予想に対する事後比較。予想の発走前保存時刻を個別検証していないため、実運用・将来の成績ではありません。','同じ標本で買い方を比較しており、未使用期間での検証は未実施。','競馬場別のBot回収率は◎軸6点の事後比較。選ばれたレースのみで、競馬場全体の稼ぎやすさを示しません。','三連複1万円以上／100円を高配当と定義。門別は除外。取消・除外など返還処理が必要な候補を含むレースは比較対象外。','馬別成績は当月の実績。名前が同じでも生年月日で区別。次走の的中確率ではありません。'],'strategies':[summary(s,race_results) for s in NAMES],'venues':venues,'marks':[{'mark':m,'n':n,'top3':t,'top3_rate':pct(t,n)} for m,(n,t) in mark_stats.items()],'horses':[{'name':n,'birth_date':b,'starts':s,'top3':t,'top3_rate':pct(t,s)} for (n,b),(s,t) in sorted(horse_stats.items(),key=lambda x:(-x[1][1],-x[1][1]/x[1][0],x[0])) if s>=3][:50],'races':race_results}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--zip',default='nar_202610.zip');p.add_argument('--predictions',default='trio_predictions.csv');p.add_argument('--out',default='trio_pwa/research.json');a=p.parse_args();d=analyze(a.zip,a.predictions);open(a.out,'w').write(json.dumps(d,ensure_ascii=False,indent=2));print(json.dumps({k:d[k] for k in ['source','strategies','marks','venues']},ensure_ascii=False,indent=2))
