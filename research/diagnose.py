"""Outcome diagnosis and explicitly retrospective counterfactuals of frozen forecasts.
No fit, no modification of forecasts. python -m research.diagnose --ledger ... --out ...
"""
import argparse,json
from collections import Counter,defaultdict
from datetime import datetime,timezone
from itertools import permutations
from pathlib import Path
from research.domain import Ledger,atomic_json
from research.metrics import summarize

VERSION='frozen-diagnosis-v1'
RULES={'candidate_set':'trio: frozen model top five; trifecta: union of saved all-races tickets',
 'outsider':'outside model top five, saved observed popularity >=6, saved career >=5 starts and top-three rate >=30%; nearest frozen rank first',
 'control':'only horses outside frozen top five, lexicographic frozen-rank permutations, cap12',
 'budget':'counterfactual fixed 12 tickets x100 maximum; underfilled plans retain unused cash; common-budget paired comparison requires exactly12',
 'adoption':'exploration of already observed periods; none adopted; future prospective confirmation required'}

def classify(candidates,tickets,paid,stake,payout,refund=0,settled=True):
    if not settled or refund:return 'D'
    winners=[tuple(p) for p in paid]
    hit=any(t in winners for t in tickets)
    if hit:return 'C' if payout<=stake else 'profitable_hit'
    return 'B' if any(set(t)<=set(candidates) for t in winners) else 'A'

def row(p,r,ts,unit,ordered=True):
    paid=r.get('official_trifecta_paybacks' if ordered else 'official_trio_paybacks') or []
    norm=lambda t:tuple(t) if ordered else tuple(sorted(t))
    ps={norm(x['numbers']):x['payback_100'] for x in paid}
    tickets={norm(t) for t in ts}
    return dict(scheduled_start=p['scheduled_start'],track=p['track'],race=p['race'],date=p['date'],
      month=p['date'][:7],stake=len(tickets)*unit,ticket_count=len(tickets),
      payout=sum(ps.get(t,0) for t in tickets)*unit//100,refund=0,
      hit=any(t in ps for t in tickets),winning_tickets=sum(t in ps for t in tickets),
      status='settled' if r.get('status')=='settled' and ps else 'pending',decision='paper_buy' if ts else 'skip')

def supported(h):
    # Only exact pre-start explanation saved by the engine; no result-derived reasons.
    import re
    for reason in h.get('reasons',[]):
        m=re.fullmatch(r'全成績: (\d+)走中(\d+)回3着以内(?:（少数標本）)?',reason)
        if m and int(m[1])>=5 and int(m[2])/int(m[1])>=.3:return True
    return False

def counterfactual(p):
    ns=[h['number'] for h in p['horses']];top=ns[:5]
    out=[h['number'] for h in p['horses'][5:] if (h.get('observed_popularity') or 0)>=6 and supported(h)]
    base=list(permutations(top[:1]+top[1:5],3))
    base=[t for t in base if t[0]==top[0]][:12]
    outsider=out[0] if out else None
    swapped=top[:4]+[outsider] if outsider else []
    return {'baseline_first12':base,
      'replace_lowest12':[t for t in permutations(swapped,3) if t[0]==swapped[0]][:12] if swapped else [],
      'outsider_second_third12':[t for t in permutations(top[:4]+[outsider],3) if t[0] in top[:2] and outsider in t[1:]][:12] if outsider else [],
      'outside_only12':list(permutations(ns[5:],3))[:12]},out

def run(ledger):
    report={'version':VERSION,'generated_at':datetime.now(timezone.utc).isoformat(),'rules':RULES,
      'ledger_head':ledger.events[-1]['hash'] if ledger.events else None,'diagnosis':{},'counterfactual':{},'missed_horses':{},
      'limitations':['実購入なし。保存予想の診断と事後比較を分離','確定オッズで予想時期待値を補完しない','近走着差・条件変更・展開・休養の入力は保存不足で不明','実発走順は未取得。DDは予定発走順','同着は公式払戻組ごとに判定。返還対象はDへ分離']}
    cf=defaultdict(list);outside=Counter()
    for kind,resultkind in [('prediction','result'),('trifecta_prediction','trifecta_result')]:
      results=ledger.latest(resultkind);groups={}
      for key,e in ledger.latest(kind).items():
        p=e['payload'];r=results.get(key,{}).get('payload',{});ordered=kind=='trifecta_prediction'
        bets={'all_races':{'tickets':p['all_races_tickets'],'unit':p['unit']},'selected':{'tickets':p['tickets'],'unit':p['unit']}} if ordered else p['strategies']
        ns=[h['number'] for h in p['horses']]
        finish=r.get('finish',[])
        for name,b in bets.items():
          g=groups.setdefault(name,{'counts':Counter(),'finish_rank':{str(i):Counter() for i in (1,2,3)},'rows':[],'reasons':Counter()})
          ts=b['tickets'];unit=b['unit'];paid=r.get('official_trifecta_paybacks' if ordered else 'official_trio_paybacks') or []
          norm=lambda t:tuple(t) if ordered else tuple(sorted(t))
          rr=r.get('strategies',{}).get(name,{})
          cand={n for t in ts for n in t} if ordered else set(ns[:5])
          category='skip' if not ts else classify(cand,[norm(t) for t in ts],[norm(x['numbers']) for x in paid],rr.get('stake',len(ts)*unit),rr.get('payout',0),rr.get('refund',0),r.get('status')=='settled' and bool(paid))
          g['counts'][category]+=1
          if category=='D':g['reasons'][r.get('reason','公式結果未取得')]+=1
          for h in finish:
            if h.get('position') in (1,2,3):g['finish_rank'][str(h['position'])][str(ns.index(h['number'])+1) if h['number'] in ns else 'unknown']+=1
          metric=row(p,r,ts,unit,ordered);metric.update(rr);metric['status']=r.get('status','pending');g['rows'].append(metric)
        if not ordered:
          for h in p['horses'][5:]:
            pos=next((x.get('position') for x in finish if x['number']==h['number']),None)
            if r.get('status')=='settled' and pos is not None:
              label='top3' if pos<=3 else 'other';outside['all_'+label]+=1
              if supported(h) and (h.get('observed_popularity') or 0)>=6:outside['eligible_'+label]+=1
          if r.get('status')=='settled' and r.get('official_trifecta_paybacks') and not any(h.get('status')=='除外' for h in finish):
            plans,_=counterfactual(p)
            for name,ts in plans.items():cf[name].append(row(p,r,ts,100))
      for name,g in groups.items():
        g['metrics']=summarize(g.pop('rows'));report['diagnosis'][kind+'/'+name]=g
    for name,rs in cf.items():
      bymonth={m:summarize([r for r in rs if r['month']==m]) for m in sorted({r['month'] for r in rs})}
      report['counterfactual'][name]={'all':summarize(rs),'monthly':bymonth,'status':'事後再構成・未採用・発走前保存戦略の実績ではない'}
    # Strict paired equal-stake comparison: same race, both exactly 1,200 yen.
    base={(r['date'],r['track'],r['race']):r for r in cf['baseline_first12']}
    for name,rs in cf.items():
      if name=='baseline_first12':continue
      paired=[r for r in rs if r['stake']==1200 and base[(r['date'],r['track'],r['race'])]['stake']==1200]
      report['counterfactual'][name]['paired_1200']={'variant':summarize(paired),'baseline':summarize([base[(r['date'],r['track'],r['race'])] for r in paired])}
    report['missed_horses']=outside
    return report

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--ledger',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);a=ap.parse_args()
    atomic_json(a.out,run(Ledger(a.ledger)))
if __name__=='__main__':main()
