"""Reproducible audit. October is inspected, every new condition exploratory."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import pickle
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
from threadpoolctl import threadpool_limits
import trio_model
import trio_engine
from research.domain import atomic_json, digest, indexed, read_archive, record_counts

def interval(hits, n):
    if not n:
        return None
    p, z = hits / n, 1.96
    mid = (p + z*z/(2*n)) / (1+z*z/n)
    half = z*math.sqrt(p*(1-p)/n+z*z/(4*n*n)) / (1+z*z/n)
    return [100*max(0,mid-half), 100*min(1,mid+half)]

def block_interval(rows, seed=20261101):
    """Resample whole dates, retaining within-day dependence, descriptive only."""
    groups = defaultdict(lambda: [0., 0.])
    for r in rows:
        groups[r['date']][0] += r['stake']
        groups[r['date']][1] += r['payout']
    if len(groups) < 2:
        return None
    a = np.array(list(groups.values()))
    rng = np.random.default_rng(seed)
    draws = a[rng.integers(0, len(a), size=(2000,len(a)))].sum(axis=1)
    return np.quantile(100*draws[:,1]/draws[:,0], [.025,.975]).tolist()

def metrics(rows):
    stake, payout = sum(r['stake'] for r in rows), sum(r['payout'] for r in rows)
    hits = sum(bool(r['hit']) for r in rows)
    return {'races': len(rows), 'hits': hits, 'hit_rate_pct': hits/len(rows)*100 if rows else None,
        'hit_wilson95_pct': interval(hits,len(rows)), 'stake': stake, 'payout': payout,
        'roi_pct': 100*payout/stake if stake else None, 'profit': payout-stake,
        'roi_day_bootstrap95_pct': block_interval(rows),
        'roi_without_largest_payout_pct': 100*(payout-max((r['payout'] for r in rows),default=0))/stake if stake else None}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', type=Path, required=True)
    ap.add_argument('--predictions', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    root = args.root
    with (root/'model_data/trio_model.pkl').open('rb') as f:
        bundle = pickle.load(f)
    raw = (root/'nar_202610.zip').read_bytes()
    data = read_archive(raw)
    races, hs, pay = indexed(data)
    groups, skips = trio_model.prepare(root/'nar_202610.zip')
    prepared = {g['key']: g for g in groups}
    old = trio_engine.analyze(root/'nar_202610.zip',args.predictions)
    old_rows = old['races']
    overlap = []
    for row in old_rows:
        key = (row['date'].replace('-',''), row['track'], str(int(''.join(c for c in row['race'] if c.isdigit()))))
        if key in prepared:
            overlap.append((row,prepared[key]))
    # 12,000 yen is divisible by all ticket counts (4,6,10,12,...).
    # If legacy unordered count is unusual, use LCM of every observed count.
    counts = {len(v['tickets']) for r,_ in overlap for v in r['strategies'].values()}
    if 0 in counts:
        raise ValueError('empty legacy tickets')
    budget = math.lcm(*counts,6,10)*100
    compared = defaultdict(list)
    with threadpool_limits(limits=1):
        _, axis = trio_model.evaluate(bundle['model'],[g for _,g in overlap],'axis6')
        _, box = trio_model.evaluate(bundle['model'],[g for _,g in overlap],'box10')
    for i,(r,g) in enumerate(overlap):
        for name,v in r['strategies'].items():
            factor = budget/v['stake']
            compared['legacy_'+name].append({'date':r['date'],'stake':budget,'payout':round(v['payout']*factor),'hit':v['hit']})
        for name,rows in [('model_axis6',axis),('model_box10',box)]:
            v = rows[i]
            compared[name].append({'date':r['date'],'stake':budget,'payout':round(v['payout']*budget/v['stake']),'hit':v['hit']})
    full = {}
    with threadpool_limits(limits=1):
        for kind in ['axis6','box10']:
            _, rows = trio_model.evaluate(bundle['model'],groups,kind)
            full[kind] = metrics(rows)
    conditions = defaultdict(lambda: [0,0])
    for month in (9,10):
        path = root/('nar_202610.zip' if month==10 else f'model_data/nar_2026{month:02}.zip')
        gs,_ = trio_model.prepare(path)
        for g in gs:
            for h,y in zip(g['horses'],g['y']):
                for field in ('全成績','当競馬場成績','うち当距離成績','騎手成績'):
                    cs = record_counts(h.get(field,''))
                    if cs is None:
                        band = '欠損'
                    elif sum(cs) < 5:
                        band = '過去5走未満'
                    else:
                        rate = sum(cs[:3])/sum(cs)
                        band = '過去3着内率50%以上' if rate>=.5 else '過去3着内率30〜50%未満' if rate>=.3 else '過去3着内率30%未満'
                    conditions[(month,field,band)][0]+=1
                    conditions[(month,field,band)][1]+=int(y)
    sample_rows = list(csv.DictReader(args.predictions.open(encoding='utf-8-sig')))
    duplicates = len(sample_rows)-len({trio_engine.key(r) for r in sample_rows})
    missing = {field:sum(not h.get(field,'').strip() for h in data['horselist']) for field in ['馬体重','馬体重増減',*trio_model.RECORDS,'着順']}
    unknown = Counter(h.get('着順','') for h in data['horselist'] if not h.get('着順','').isdigit())
    payout_duplicates=sum(len(v)-len({digest(p) for p in v}) for v in pay.values())
    report = {'generated_at':datetime.now(timezone.utc).isoformat(), 'period':'2026-10-01..2026-10-31',
        'status':'既閲覧期間の事後監査。新規最終評価ではありません',
        'reproduced': {'legacy_matched':len(old_rows),'model_races':len(groups),'full_model':full},
        'quality':{'official_race_rows':len(data['racelist']),'horse_rows':len(data['horselist']),'model_exclusions':skips,
            'legacy_duplicate_race_rows':duplicates,'identical_duplicate_payback_rows':payout_duplicates,
            'blank_fields':missing,'unknown_finish_values':dict(unknown),
            'race_and_horse_keys':'日付・競馬場・レース番号・馬番。馬名結合は推論に使いません'},
        'equal_budget_comparison':{'races':len(overlap),'legacy_total_matched':len(old_rows),'model_total':len(groups),
            'budget_per_race':budget,'budget_reason':'全方式の点数の最小公倍数×100円。比較専用・推奨購入額ではありません',
            'strategies':{k:metrics(v) for k,v in compared.items()},
            'limitations':['新旧とも利用可能なレースの共通部分のみ。選択偏りあり。',
                '旧予想の事前保存を全件独立確認していません。新旧の優劣を確定できません。',
                '日単位ブートストラップ95%区間はこの標本内の不確実性。将来の保証ではありません。']},
        'conditions':[{'month':m,'field':f,'condition':c,'n':n,'top3':t,'top3_rate_pct':t/n*100,'wilson95_pct':interval(t,n)} for (m,f,c),(n,t) in sorted(conditions.items())],
        'condition_status':'9月・10月とも閲覧済みの探索的集計。穴馬採用・見送りの収益優位性は未検証。人気・確定オッズで選別しません。',
        'prospective':{'start':'研究パイプラインの初回配備後、発走5分より前に固定した予想のみ',
            'strategy':'軸6点と5頭BOX10点を各レース3,000円の同予算で記録。実購入なし。',
            'model_selection':'7〜8月学習・9月Brierで選択。10月は既閲覧。11月の事前保存予想を別集計。'},
        'findings':['旧177Rとモデル985Rの回収率・的中数を再現。黒字化は未達。',
            '空欄着順を含むレースはモデル評価から除外されている。取消・除外・中止の区別はCSV単独で未解決。',
            '同着は複数払戻行を重複排除して計算。払戻組番の競合は実運用で停止。',
            '旧エンジンは正数着順以外を除外するため、中止等も取消と一緒に除外し得る。',
            '特徴量を許可リストに制限。確定着順・人気・タイム・払戻は入力禁止。',
            '馬体重は発走前取得可能だが早朝には欠損し得るため、当日運用は発表まで待機。',
            'ROI最大値や高配当頻度から競馬場を選ぶ最適化は行っていない。',
            '原コードの同日レース順を文字列番号から発走時刻・数値番号へ修正。累積損失指標に影響。',
            'モデルは人気を使わない順位付け。高スコアの馬を穴馬や期待値プラスと認定しない。'],
        'sources':[{'title':'公式CSV説明書','url':'https://www.keiba.go.jp/pdf/manual/data_pdf_manual.pdf'},
            {'title':'公式利用規約','url':'https://www.keiba.go.jp/terms.html'}]}
    atomic_json(args.out,report)
    print(json.dumps({'common_races':len(overlap),'equal_budget':budget,'strategies':{k:(v['hits'],round(v['roi_pct'],2)) for k,v in report['equal_budget_comparison']['strategies'].items()}},ensure_ascii=False))

if __name__=='__main__':
    main()
