"""Separate immutable ordered-ticket journal. Never amends legacy forecasts."""
import hashlib,json,pickle
from pathlib import Path
from datetime import datetime,timedelta
from itertools import permutations
from threadpoolctl import threadpool_limits
from research.domain import digest,allowlisted,evidence,start_time
from research.trifecta import snapshot,payouts,VERSION
from research.strategies import concerns
from research.metrics import summarize

def freeze(state,ledger,key,hs,race,meta,now):
    if key in ledger.latest('trifecta_prediction'):return
    path=Path(state)/'trifecta_model.pkl';mp=Path(state)/'trifecta_model_meta.json'
    try:
        remaining=(start_time(race)-now).total_seconds()
        if not 300<remaining<=3600 or any(str(h.get('着順','')).strip() for h in hs):raise ValueError('発走前の固定時間外・結果混在。三連単を遡及生成しません')
        if not path.exists() or not mp.exists():raise ValueError('三連単研究モデル未配置。新規予想は生成しません')
        raw=path.read_bytes();info=json.loads(mp.read_text())
        if hashlib.sha256(raw).hexdigest()!=info['sha256'] or info['version']!=VERSION:raise ValueError('三連単モデル検証失敗')
        bundle=pickle.loads(raw);limitpath=Path(state)/'trifecta_limits.json';limits=json.loads(limitpath.read_text()) if limitpath.exists() else {'cap':12,'unit':100,'max_stake':1200}
        clean,context=allowlisted(hs,race);pop={int(h['馬番']):int(h['人気']) for h in hs if str(h.get('人気','')).isdigit() and int(h['人気'])>0}
        with threadpool_limits(limits=1):p=snapshot(bundle['model'],clean,context,pop,meta,**limits)
        p.update(date=now.astimezone(__import__('research.domain',fromlist=['JST']).JST).date().isoformat(),track=race['競馬場'],race=int(race['レース番号']),time=str(race['発走時刻']).zfill(4)[:2]+':'+str(race['発走時刻']).zfill(4)[2:],race_name=race.get('レース名',''),scheduled_start=__import__('research.domain',fromlist=['start_time']).start_time(race).isoformat(),
            fixed_at=now.isoformat(),source_at=meta['source_at'],fetched_at=meta['fetched_at'],model_sha256=info['sha256'],input_sha256=digest({'horses':clean,'race':context}),limits=limits,paper_only=True,
            horses=[{'number':int(h['馬番']),'name':h['馬名'],'position_ranks':p['position_ranks'][int(h['馬番'])],'reasons':evidence(h),'concerns':concerns(h),'observed_popularity':pop.get(int(h['馬番']))} for h in clean])
        p['horses'].sort(key=lambda h:(sum(h['position_ranks']),h['number']))
        ledger.append('trifecta_prediction',key,p,now)
    except (ValueError,KeyError,TypeError,OSError) as e:
        payload={'reason':str(e),'strategy_version':VERSION};old=ledger.latest('trifecta_observation').get(key)
        if not old or old['payload']!=payload:ledger.append('trifecta_observation',key,payload,now)

def settle_ordered(p,hs,ps):
    if {int(h['馬番']) for h in hs}!={h['number'] for h in p['horses']}:return {'status':'review_required','reason':'出走馬増減・返還要照合'}
    if any((not str(h.get('着順','')).isdigit() and h.get('着順')!='中止') or str(h.get('着順','')).isdigit() and int(h['着順'])<1 for h in hs):return {'status':'review_required','reason':'着順空欄・取消・除外・返還要照合'}
    try:paid=payouts(ps)
    except ValueError as e:return {'status':'review_required','reason':str(e)}
    if not paid:return {'status':'pending','reason':'公式三連単払戻未取得'}
    finish={int(h['馬番']):int(h['着順']) for h in hs if str(h['着順']).isdigit()}
    pool={n for n,r in finish.items() if r<=3};expected=set()
    for t in permutations(pool,3):
        rr=[finish[n] for n in t];lower={n for n,r in finish.items() if r<max(rr)}
        if rr==sorted(rr) and lower<=set(t):expected.add(t)
    if set(paid)!=expected:return {'status':'review_required','reason':'三連単着順・同着払戻行の完全性未確認'}
    out={}
    for name,ts in [('selected',p['tickets']),('all_races',p['all_races_tickets'])]:
        if len(ts)!=len(set(tuple(t) for t in ts)) or any(len(set(t))!=3 or len(t)!=3 for t in ts) or p['unit']%100 or p['unit']<100:return {'status':'review_required','reason':'保存買い目・購入単位が不正'}
        ts={tuple(t) for t in ts};hits=[t for t in ts if t in paid]
        out[name]={'stake':len(ts)*p['unit'],'payout':sum(paid[t] for t in hits)*p['unit']//100,'refund':0,'hit':bool(hits),'winning_tickets':len(hits),'ticket_count':len(ts),'decision':'paper_buy' if ts else 'skip'}
    return {'status':'settled','strategies':out,'finish':[{'number':int(h['馬番']),'position':int(h['着順']) if str(h['着順']).isdigit() else None,'status':h['着順']} for h in hs],'official_trifecta_paybacks':[{'numbers':list(t),'payback_100':v} for t,v in paid.items()],'reason':'公式三連単全払戻行と照合'}

def reconcile(ledger,horses,paybacks,meta,now):
    old=ledger.latest('trifecta_result')
    for k,e in ledger.latest('trifecta_prediction').items():
        if k not in horses or now<datetime.fromisoformat(e['payload']['scheduled_start'])+timedelta(minutes=3):continue
        result=settle_ordered(e['payload'],horses[k],paybacks.get(k,[]));result['source']=meta
        prior=old.get(k,{}).get('payload',{});core=lambda d:{k:v for k,v in d.items() if k!='source'}
        if core(prior)!=core(result):ledger.append('trifecta_result',k,result,now)

def public(ledger):
    results=ledger.latest('trifecta_result');rows=[]
    for k,e in ledger.latest('trifecta_prediction').items():rows.append(dict(e['payload'],race_key=k,commitment=e['hash'],result=results.get(k,{}).get('payload',{'status':'pending','reason':'公式結果待ち'})))
    summary={}
    for name in ['selected','all_races']:
        metrics=[]
        for p in rows:
            ts=p['tickets'] if name=='selected' else p['all_races_tickets'];r=p['result'];m={'scheduled_start':p['scheduled_start'],'track':p['track'],'race':p['race'],'stake':len(ts)*p['unit'],'ticket_count':len(ts),'decision':'paper_buy' if ts else 'skip','status':r['status']}
            m.update(r.get('strategies',{}).get(name,{}));metrics.append(m)
        summary[name]=summarize(metrics)
    return {'version':VERSION,'races':rows,'summary':summary,'status':'検証中・実購入なし'}
