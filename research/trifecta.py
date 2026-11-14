"""Ordered-ticket research. Scores are ordinal field ranks, never joint probabilities."""
import json
from pathlib import Path
from itertools import permutations, combinations
import numpy as np
import trio_model
from research.domain import record_counts, digest

SPEC=json.loads(Path(__file__).with_name('trifecta_spec.json').read_text())
VERSION=SPEC['version']

def payouts(rows):
    result={}
    for p in rows:
        ns=[str(p.get('３連単組番馬番'+str(i),'')).strip() for i in (1,2,3)]
        amount=str(p.get('３連単払戻金（円）','')).replace(',','').strip()
        if not any(ns) and not amount:continue
        if not all(n.isdigit() for n in ns) or not amount.isdigit():raise ValueError('返還・特殊払戻の照合が必要')
        t=tuple(map(int,ns));v=int(amount)
        if len(set(t))!=3 or min(t)<1 or v<1:raise ValueError('不正な三連単払戻')
        if t in result and result[t]!=v:raise ValueError('三連単払戻の競合')
        result[t]=v
    return result

def assessment(horses, ranks):
    cs=[record_counts(h.get('全成績','')) for h in horses]
    rates=sorted([sum(c[:3])/sum(c) for c in cs if c and sum(c)>0],reverse=True)
    # Unlike score spread, this ability-gap proxy has a fixed interpretable scale.
    gap=rates[0]-rates[1] if len(rates)>1 else None
    minimum=min((sum(c) for c in cs if c),default=0)
    selected=len(horses)>=SPEC['selection']['min_runners'] and gap is not None and gap<=SPEC['selection']['max_top3_score_gap'] and minimum>=SPEC['selection']['min_axis_record_starts']
    return {'decision':'paper_candidate' if selected else 'skip',
        'label':'能力差が小さいという探索仮説' if selected else '選別条件に届かず見送り',
        'ability_gap':gap,'min_record_starts':minimum,'runners':len(horses),
        'reasons':[f'頭数{len(horses)}、全成績3着内率の上位差{gap:.3f}' if gap is not None else '累積成績不足',
            '出走全馬に5走以上の累積成績が必要'],
        'limitations':['荒れる確率・利益を示すものではない','展開・昇級・休養・馬場変化は今回未評価']}

def position_ranks(model, horses, race):
    raw=model.predict_proba(trio_model.features(horses,race)); ns=[int(h['馬番']) for h in horses]
    ratings={n:[] for n in ns}
    for pos in (1,2,3):
        col=list(model.classes_).index(pos)
        order=sorted(range(len(ns)),key=lambda i:(-raw[i,col],ns[i]))
        for rank,i in enumerate(order,1):ratings[ns[i]].append(rank)
    return ratings

def ticket_sets(numbers, ranks, horses, popularity, cap=12):
    ns=list(numbers); order=sorted(ns,key=lambda n:(sum(ranks[n]),n));axis=order[0]
    def ordered(ts):return sorted(set(tuple(t) for t in ts if len(set(t))==3),key=lambda t:(sum(ranks[n][i] for i,n in enumerate(t)),t))[:cap]
    first=ordered((axis,b,c) for b in order[1:5] for c in order[1:5] if b!=c)
    spread=ordered((a,b,c) for a in order[:2] for b in order[:3] for c in order[:6] if len({a,b,c})==3)
    by={int(h['馬番']):h for h in horses}
    outsiders=[]
    for n in order[:6]:
        cs=record_counts(by[n].get('全成績','')); ds=record_counts(by[n].get('うち当距離成績',''))
        if popularity.get(n,0)>=6 and cs and sum(cs)>=5 and sum(cs[:3])/sum(cs)>=.3 and ds and sum(ds)>=3 and sum(ds[:3])/sum(ds)>=.3:outsiders.append(n)
    hole_first=ordered((a,b,c) for a in outsiders for b in order[:3] for c in order[:5] if len({a,b,c})==3)
    hole_third=ordered((a,b,c) for a in order[:2] for b in order[:3] for c in outsiders if len({a,b,c})==3)
    multi=ordered(t for n in order[2:5] for t in permutations((order[0],order[1],n))) if len(order)>=5 else []
    return {'first':first,'spread':spread,'hole_first':hole_first,'hole_third':hole_third,'two_axis_multi':multi},outsiders

def snapshot(model,horses,race,popularity,source,cap=12,unit=100,max_stake=1200):
    if unit%100 or unit<100 or cap<1 or max_stake<100:raise ValueError('invalid research limits')
    cap=min(cap,max_stake//unit)
    ns=[int(h['馬番']) for h in horses]; ranks=position_ranks(model,horses,race)
    bets,holes=ticket_sets(ns,ranks,horses,popularity,cap)
    assess=assessment(horses,ranks)
    chosen=bets['spread'] if assess['decision']=='paper_candidate' else []
    return {'strategy_version':VERSION,'spec_sha256':digest(SPEC),'assessment':assess,
        'position_ranks':ranks,'outsider_numbers':holes,'tickets':chosen,'all_races_tickets':bets['spread'],
        'alternatives':bets,'unit':unit,'stake':len(chosen)*unit,'max_points':cap,'max_stake':max_stake,
        'odds':{},'odds_status':'未取得。予想時三連単オッズがないため期待値の検証不能',
        'source':source,'score_status':'同一出馬表内の着順別順位スコア。組合せ確率・校正済み確率ではない',
        'status':'検証中・紙上運用・実購入なし'}
