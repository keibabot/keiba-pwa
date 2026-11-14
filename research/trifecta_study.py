"""Small preregistered replay; does not retune until profit appears."""
import argparse, json, pickle, hashlib, csv
from pathlib import Path
from collections import Counter,defaultdict
from datetime import datetime,timezone
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from threadpoolctl import threadpool_limits
import trio_model
from research.domain import read_archive,indexed,start_time,EXCLUDED,canonical,atomic_json,winners
from research.trifecta import SPEC,VERSION,payouts,position_ranks,ticket_sets,assessment
from research.metrics import summarize

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--state',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);ap.add_argument('--private',type=Path,required=True)
    a=ap.parse_args();a.private.mkdir(parents=True,exist_ok=True)
    months={};quality=[];exclusions=[];sources=[]
    for m in (7,8,9,10):
        path=a.state/f'training/nar_2026{m:02}.zip';raw=path.read_bytes();data=read_archive(raw);ra,hs,ps=indexed(data)
        gs,sk=trio_model.prepare(path);valid=[]
        for g in gs:
            k='|'.join([g['key'][0],g['key'][1],str(int(g['key'][2]))]);reason=None
            try:
                paid=payouts(ps[k]);fs=[str(h.get('着順','')).strip() for h in hs[k]]
                if len(hs[k])!=len(g['horses']):raise ValueError('取消・除外を事後除去したレース')
                if not all(f.isdigit() and int(f)>0 for f in fs):raise ValueError('着順不明・返還要照合')
                if len(fs)!=len(set(fs)):raise ValueError('同着の新三連単学習・比較は保留（払戻保存は対応）')
                expected=tuple(int(h['馬番']) for h in sorted(hs[k],key=lambda h:int(h['着順']))[:3])
                if not paid or set(paid)!={expected}:raise ValueError('三連単払戻未取得・着順と不整合')
                g['trifecta']=paid;g['race_key']=k;valid.append(g)
            except ValueError as e:reason=str(e)
            if reason:exclusions.append({'month':m,'race_key':k,'reason':reason})
        prepared_keys={g['race_key'] for g in valid}
        for k,r in ra.items():
            if k not in prepared_keys and not any(e['race_key']==k for e in exclusions):exclusions.append({'month':m,'race_key':k,'reason':'対象外場' if r['競馬場'] in EXCLUDED else 'モデル元処理の着順空欄・頭数不足等'})
        months[m]=valid
        fields=['馬体重','負担重量','全成績','当競馬場成績','うち当距離成績','騎手成績','着順']
        quality.append({'month':m,'official_races':len(ra),'model_prepared':len(gs),'eligible':len(valid),'excluded':len(ra)-len(valid),'venues':dict(Counter(g['key'][1] for g in valid)),
            'horse_rows':len(data['horselist']),'blank_rate_pct':{f:100*sum(not h.get(f,'').strip() for h in data['horselist'])/len(data['horselist']) for f in fields},'base_skips':sk})
        sources.append({'month':m,'sha256':hashlib.sha256(raw).hexdigest(),'url':f'https://www.keiba.go.jp/KeibaWeb/DataDownload/RaceDataDownload?k_year=2026&k_month={m}&type=monthly'})
    meta=json.loads((a.state/'model_meta.json').read_text()); rawmodel=(a.state/'model.pkl').read_bytes()
    if hashlib.sha256(rawmodel).hexdigest()!=meta['sha256']:raise ValueError('Existing model checksum mismatch')
    old=pickle.loads(rawmodel)['model']
    rows=[];folds=[];last_model=None
    with threadpool_limits(limits=1):
        for trainmonths,validation,test in [([7],8,9),([7,8],9,10)]:
            train=[g for m in trainmonths for g in months[m]]; X=np.concatenate([g['X'] for g in train]);y=np.concatenate([np.array([int(h['着順']) if int(h['着順'])<=3 else 0 for h in g['horses']]) for g in train])
            model=HistGradientBoostingClassifier(max_iter=150,max_leaf_nodes=15,min_samples_leaf=80,l2_regularization=10,learning_rate=.06,random_state=42)
            model.fit(X,y);last_model=model
            validation_n=len(months[validation]);fold=f'test_{test}'
            for g in months[test]:
                hs=g['horses'];ns=[int(h['馬番']) for h in hs];ranks=position_ranks(model,hs,g['race']);pop={int(h['馬番']):int(h['人気']) for h in hs if h.get('人気','').isdigit() and int(h['人気'])>0}
                assess=assessment(hs,ranks);truepaid=g['trifecta'];trio=g['winners'];high=max(truepaid.values())>=SPEC['high_payout_yen_per_100'];base={'race_key':g['race_key'],'date':g['key'][0],'track':g['key'][1],'race':int(g['key'][2]),'month':test,'fold':fold,'scheduled_start':start_time(g['race']).isoformat(),'high_payout_label_A':high,'status':'settled','prediction_status':'過去再生成・既閲覧期間','going':g['race'].get('馬場','不明'),'distance':g['race']['距離']}
                def add(name,ts,unit=100,unordered=False,decision=None):
                    paid=dict(trio) if unordered else truepaid;ts=list(dict.fromkeys(tuple(sorted(t)) if unordered else tuple(t) for t in ts));hit=[t for t in ts if t in paid]
                    rows.append({**base,'strategy':name,'tickets':ts,'ticket_count':len(ts),'unit':unit,'stake':unit*len(ts),'payout':sum(paid[t] for t in hit)*unit//100,'hit':bool(hit),'winning_tickets':len(hit),'refund':0,'decision':decision or ('paper_buy' if ts else 'skip'),'high_payout_hit':high and bool(hit),'selection':assess})
                scores=np.array([sum(ranks[n]) for n in ns]);order=sorted(ns,key=lambda n:(sum(ranks[n]),n))
                # Existing frozen v1 model is evaluated separately, without retraining it.
                oldscores=old.predict_proba(g['X'])[:,1]
                for kind,unit in [('axis6',100),('box10',100)]:add('existing_'+kind,trio_model.picks(ns,oldscores,kind),unit,True)
                # Monthly popularity reference never enters model features or live selection.
                popular=sorted(ns,key=lambda n:(pop.get(n,999),n));p_rank={n:[i+1]*3 for i,n in enumerate(popular)}
                if len(pop)==len(ns):
                    p_bets,_=ticket_sets(ns,p_rank,hs,pop,12);add('final_popularity_first12_reference',p_bets['first'])
                else:add('final_popularity_first12_reference',[],decision='unavailable')
                for cap in SPEC['point_caps_tested']:
                    bs,holes=ticket_sets(ns,ranks,hs,pop,cap)
                    for name,ts in bs.items():add(name+f'_{cap}',ts)
                    add(f'selected_spread_{cap}',bs['spread'] if assess['decision']=='paper_candidate' else [])
                # Equal-stake subset: 6000 yen divides 6/10/12 points in legal 100-yen units.
                first12,_=ticket_sets(ns,ranks,hs,pop,12)
                for name,ts,un in [('equal_existing_axis6',trio_model.picks(ns,oldscores,'axis6'),True),('equal_existing_box10',trio_model.picks(ns,oldscores,'box10'),True),('equal_first12',first12['first'],False)]:
                    if len(ts) in (6,10,12):add(name,ts,6000//len(ts),un)
            folds.append({'training_months':trainmonths,'validation_month':validation,'test_month':test,'training_races':len(train),'validation_races':validation_n,'test_races':len(months[test]),'status':'既閲覧の時系列分離。利益でモデル・閾値を調整していない'})
            print('completed',fold,flush=True)
    groups=defaultdict(list)
    for r in rows:groups[r['strategy']].append(r)
    summary={s:summarize(v) for s,v in groups.items()}
    slices=[]
    for dim in ['month','track','high_payout_label_A']:
        for val in sorted({str(r[dim]) for r in rows}):
            for s in ['spread_12','selected_spread_12','existing_axis6','existing_box10','final_popularity_first12_reference']:
                subset=[r for r in groups[s] if str(r[dim])==val];slices.append({'dimension':dim,'value':val,'strategy':s,**summarize(subset)})
    labels={}
    for label in ('all','selected'):
        rr=groups['spread_12'] if label=='all' else groups['selected_spread_12'];bought=[r for r in rr if r['stake']>0]
        labels[label]={'target_races':len(rr),'bought_races':len(bought),'high_payout_races':sum(r['high_payout_label_A'] for r in bought),'high_payout_rate_pct':100*sum(r['high_payout_label_A'] for r in bought)/len(bought) if bought else None,'high_payout_hits':sum(r['high_payout_hit'] for r in bought)}
    bundle={'model':last_model,'version':VERSION,'trained_until':'20260831','spec_sha256':__import__('research.domain',fromlist=['digest']).digest(SPEC)}
    blob=pickle.dumps(bundle);(a.private/'trifecta_model.pkl').write_bytes(blob)
    atomic_json(a.private/'trifecta_model_meta.json',{'sha256':hashlib.sha256(blob).hexdigest(),'version':VERSION,'trained_until':'20260831'})
    report={'version':VERSION,'spec':SPEC,'generated_at':datetime.now(timezone.utc).isoformat(),'sources':sources,'quality':quality,'folds':folds,'strategies':summary,'slices':slices,'label_A':labels,
        'label_B':'発走前人気薄の上位入線は月次だけでは未検証。最終人気による基準・穴位置比較は事後参考分析',
        'label_C':'市場との乖離は観測人気と評価順位の差だけ。三連単の予想時オッズ・校正済み組合せ確率がなく期待値の検証不能',
        'adoption':'未採用・検証中。独立未使用期間で改善を確認していない',
        'limitations':['18点は初期上限外の感度分析。初期設定は12点・1200円・各100円','同額比較は6000円の研究用別計算。18点・可変点数の穴方式は同額比較へ混ぜない','実際の発走時刻は未取得。DD・連敗は予定発走順の参考値','取消等・同着を含む新三連単モデル評価は保留し全除外理由を保存','近走着差・脚質・通過順位・休養・昇級・調教は今回のモデルに未採用。現在レースの結果入力は禁止','高配当率の高い競馬場を購入条件に使わない','三連複は既存固定モデル。新三連単は着順別順位の加算スコアで組合せ確率ではない','評価期間9月には既存モデルの選択に使ったデータを含む。全て探索的比較']}
    atomic_json(a.out,report)
    for name,data in [('trifecta_rows.jsonl',rows),('trifecta_exclusions.jsonl',exclusions)]:
        (a.private/name).write_text(''.join(canonical(r)+'\n' for r in data))
    print(canonical({k:{'races':v['bought_races'],'hits':v['hits'],'roi':v['roi_pct']} for k,v in summary.items()}))
if __name__=='__main__':main()
