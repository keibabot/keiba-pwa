"""Private-original replay. All supplied months are marked inspected, never a fresh final test.

python -m research.study --archives /private/months --model /private/model.pkl
  --model-meta /private/model_meta.json --predictions /private/predictions.csv
  --out strategy_report.json --rows /private/study_rows.jsonl [--rolling]
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import pickle
import numpy as np
from threadpoolctl import threadpool_limits
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.metrics import brier_score_loss
import trio_model
import trio_engine
from research.domain import EXCLUDED, atomic_json, indexed, read_archive, settle, start_time, canonical
from research.metrics import summarize
from research.strategies import baskets, VERSION, RULES, RULE_SHA256, BUDGET, pack

def load_month(path):
    data = read_archive(path.read_bytes())
    races, horses, pays = indexed(data)
    groups, skips = trio_model.prepare(path)
    return groups, races, horses, pays, skips

def evaluate(groups, model, horses, pays, fold):
    rows = []
    rejected = Counter()
    for g in groups:
        key = '|'.join((g['key'][0], g['key'][1], str(int(g['key'][2]))))
        hs = horses[key]
        if len(hs) < 6:
            rejected['6頭未満'] += 1
            continue
        scores = model.predict_proba(g['X'])[:, 1]
        ranked = [int(g['horses'][i]['馬番']) for i in sorted(range(len(scores)), key=lambda i: (-scores[i], int(g['horses'][i]['馬番'])))]
        popular = {int(h['馬番']): int(h['人気']) for h in hs if str(h.get('人気', '')).isdigit() and int(h['人気']) > 0}
        if len(popular) != len(hs) or len(set(popular.values())) != len(hs):
            rejected['確定人気欠損・重複（全方式の共通参考標本から除外）'] += 1
            continue
        # Monthly final popularity is ONLY a descriptive reference, never a live observation.
        bs = baskets(ranked, hs, popular)
        pred = {'horses': [{'number': int(h['馬番'])} for h in hs], 'strategies': bs}
        result = settle(pred, hs, pays[key])
        for strategy, bet in bs.items():
            outcome = result.get('strategies', {}).get(strategy, {})
            paid = {tuple(sorted(map(int, [p.get('３連複組番馬番'+str(i), 0) or 0 for i in (1, 2, 3)]))) for p in pays[key]
                    if str(p.get('３連複払戻金（円）', '')).isdigit()}
            rows.append({'race_key': key, 'date': g['key'][0], 'track': g['key'][1], 'race': int(g['key'][2]),
                'scheduled_start': start_time(g['race']).isoformat(), 'fold': fold, 'strategy': strategy,
                'distance_band': '1200m以下' if int(g['race']['距離']) <= 1200 else '1300〜1600m' if int(g['race']['距離']) <= 1600 else '1700m以上',
                'going': g['race'].get('馬場', '') or '不明', 'surface': g['race'].get('芝ダート区分', '') or '不明',
                'runners_band': '6〜7頭' if len(hs) <= 7 else '8〜10頭' if len(hs) <= 10 else '11頭以上',
                **bet, 'ticket_count': len(bet['tickets']), 'winning_tickets': sum(tuple(t) in paid for t in bet['tickets']) if result['status'] == 'settled' else None,
                'status': result['status'], 'settlement_reason': result['reason'],
                'payout': outcome.get('payout', 0), 'refund': outcome.get('refund', 0), 'hit': outcome.get('hit', False),
                'popularity_status': '月次の確定人気。人気基準・穴条件は事後の参考分析のみ',
                'prediction_status': '過去再生成。発走前保存実績ではない'})
    return rows, dict(rejected)

def aggregation(rows):
    return {s: summarize([r for r in rows if r['strategy'] == s]) for s in sorted({r['strategy'] for r in rows})}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--archives', type=Path, required=True)
    ap.add_argument('--model', type=Path, required=True)
    ap.add_argument('--model-meta', type=Path, required=True)
    ap.add_argument('--predictions', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--rows', type=Path, required=True)
    ap.add_argument('--rolling', action='store_true')
    args = ap.parse_args()
    meta = json.loads(args.model_meta.read_text())
    model_raw = args.model.read_bytes()
    if hashlib.sha256(model_raw).hexdigest() != meta['sha256']:
        raise ValueError('trusted private model hash mismatch')
    bundle = pickle.loads(model_raw)
    months = {m: load_month(args.archives / f'nar_2026{m:02}.zip') for m in range(3, 11)}
    rows = []; folds = []; exclusions = {}
    with threadpool_limits(limits=1):
        for m in (9, 10):
            gs, races, hs, pay, skip = months[m]
            values, extra = evaluate(gs, bundle['model'], hs, pay, f'fixed_v1_{m:02}')
            rows.extend(values)
            exclusions[str(m)] = {'official_total': len(races), 'excluded_track_races': sum(r['競馬場'] in EXCLUDED for r in races.values()),
                'model_prepare': skip, 'study_extra': extra, 'prepared': len(gs),
                'study_target': len({r['race_key'] for r in values})}
        if args.rolling:
            for test_month in range(7, 11):
                training = list(range(test_month - 4, test_month - 1))
                validation = test_month - 1
                tr = [g for m in training for g in months[m][0]]; va = months[validation][0]
                X = np.concatenate([g['X'] for g in tr]); y = np.concatenate([g['y'] for g in tr])
                VX = np.concatenate([g['X'] for g in va]); vy = np.concatenate([g['y'] for g in va])
                candidates = {'hist_gradient': HistGradientBoostingClassifier(max_iter=150, max_leaf_nodes=15, min_samples_leaf=80, l2_regularization=10, learning_rate=.06, random_state=42),
                    'logistic': make_pipeline(SimpleImputer(add_indicator=True), StandardScaler(), LogisticRegression(max_iter=1000, C=.3))}
                scores = {}
                for name, model in candidates.items():
                    model.fit(X, y); scores[name] = float(brier_score_loss(vy, model.predict_proba(VX)[:, 1]))
                selected = min(scores, key=scores.get)
                gs, _, hs, pay, skip = months[test_month]
                values, extra = evaluate(gs, candidates[selected], hs, pay, f'rolling_{test_month:02}')
                rows.extend(values)
                folds.append({'train_months': training, 'selection_month': validation, 'replay_month': test_month,
                    'train_races': len(tr), 'selection_races': len(va), 'brier': scores, 'selected': selected,
                    'prepare_exclusions': skip, 'extra_exclusions': extra,
                    'strategies': aggregation(values), 'status': '時系列分離の過去再現。既閲覧期間・未使用最終評価ではない'})
                print('completed rolling', test_month, flush=True)
    fixed_rows = [r for r in rows if r['fold'].startswith('fixed')]
    legacy = trio_engine.analyze(args.archives / 'nar_202610.zip', args.predictions)
    legacy_by = {f"{r['date'].replace('-', '')}|{r['track']}|{int(''.join(c for c in r['race'] if c.isdigit()))}": r for r in legacy['races']}
    common_keys = set(legacy_by) & {r['race_key'] for r in fixed_rows if r['fold'] == 'fixed_v1_10' and r['status'] == 'settled'}
    common = [r for r in fixed_rows if r['race_key'] in common_keys]
    for key in sorted(common_keys):
        template = next(r for r in common if r['race_key'] == key)
        for strategy, old in legacy_by[key]['strategies'].items():
            ts = [tuple(map(int, t.split('-'))) for t in old['tickets']]
            bet = pack(ts)
            common.append({**template, **bet, 'strategy': 'legacy_' + strategy, 'ticket_count': len(ts),
                'winning_tickets': 0,
                'payout': old['payout'] * (bet['unit'] // 100), 'hit': old['hit'],
                'prediction_status': '旧保存予想。事前保存の独立証明は別監査。仮想購入'})
    # Exact winning-ticket count for legacy, including multiple dead-heat winners.
    from research.domain import winners
    for r in common:
        if r['strategy'].startswith('legacy_'):
            paid = winners(months[10][3][r['race_key']])
            r['winning_tickets'] = sum(tuple(t) in paid for t in r['tickets'])
    slices = []
    for dimension in ('track', 'distance_band', 'going', 'runners_band', 'surface'):
        for value in sorted({r[dimension] for r in fixed_rows}):
            for month in (9, 10):
                subset = [r for r in fixed_rows if r[dimension] == value and r['fold'] == f'fixed_v1_{month:02}']
                slices.append({'dimension': dimension, 'value': value, 'month': month, 'strategies': aggregation(subset)})
    rolling_rows = [r for r in rows if r['fold'].startswith('rolling')]
    report = {'schema_version': 1, 'version': VERSION, 'rules_sha256': RULE_SHA256,
        'generated_at': datetime.now(timezone.utc).isoformat(), 'rules': RULES, 'budget_per_opportunity': BUDGET,
        'adoption': '未採用。全ルールは研究候補。改善・将来収益の独立確認なし',
        'status': '既閲覧期間の探索的・時系列分離の過去再現。未使用最終評価ではない',
        'exclusions': exclusions, 'fixed_v1': {str(m): aggregation([r for r in fixed_rows if r['fold'] == f'fixed_v1_{m:02}']) for m in (9, 10)},
        'rolling_folds': folds, 'rolling_pooled': aggregation(rolling_rows),
        'legacy_common': {'races': len(common_keys), 'budget': BUDGET, 'strategies': aggregation(common)},
        'slices': slices, 'sources': [{'month': m, 'sha256': hashlib.sha256((args.archives/f'nar_2026{m:02}.zip').read_bytes()).hexdigest(),
            'url': f'https://www.keiba.go.jp/KeibaWeb/DataDownload/RaceDataDownload?k_month={m}&k_year=2026&type=monthly'} for m in range(3, 11)],
        'model_sha256': meta['sha256'], 'actual_purchase': False,
        'limitations': ['月次人気は確定値。人気基準と穴条件は参考分析。予想時人気による優位性は未検証',
            '1機会6,000円は4・6・10点を100円単位で揃える比較専用予算。見送り資金は再配分しない',
            '全ルールを掲載し、最大ROIだけを選ばない。少数標本・多重比較・高配当依存が残る',
            '予定発走時刻順で計算。実発走順の最大DDと最大連敗は未検証',
            '取消・返還不明・着順空欄は除外／要照合を表示。除外標本への選択偏りは解消しない',
            '過去期間の事後再生成であり、実購入実績・全件発走前保存実績ではない',
            '次の独立評価は本版配備後の事前記録のみ。閾値変更時は版と適用日を分ける。11月全体を未使用とは呼ばない']}
    atomic_json(args.out, report)
    args.rows.parent.mkdir(parents=True, exist_ok=True)
    with args.rows.open('w') as f:
        for r in rows + [r for r in common if r['strategy'].startswith('legacy_')]:
            f.write(canonical(r) + '\n')
    print(canonical({'fixed': report['fixed_v1'], 'common_races': len(common_keys), 'rolling': report['rolling_pooled']}))

if __name__ == '__main__':
    main()
