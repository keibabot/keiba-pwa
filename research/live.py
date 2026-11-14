"""One-shot official ingestion -> frozen paper forecasts -> official settlement.

Run inside the private Bot workflow. Raw official files and models stay private.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import pickle
import re
import sys
import time
import urllib.request
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
from threadpoolctl import threadpool_limits
from research.domain import (EXCLUDED, JST, SCHEMA, Ledger, allowlisted, atomic_json,
    canonical, digest, evidence, indexed, read_archive, record_counts, settle, start_time)
import trio_model
from research import trifecta_live
from research.official_status import enrich
from research.strategies import baskets, concerns, VERSION as BASKET_VERSION, RULE_SHA256, BUDGET
from research.metrics import summarize

DAILY_URL = 'https://www.keiba.go.jp/KeibaWeb/DataDownload/RaceDataDownload?type=daily'
VERSION = 'trio-paper-v3-independent-reconciliation'

def fetch_daily(state, now):
    """Durable timestamp enforces >=120s across runners, including failed attempts."""
    meta_path = state / 'daily_meta.json'
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    path = state / 'daily.zip'
    if time.time() - meta.get('attempt_epoch', 0) < 120:
        if not path.exists() or not meta.get('ok'):
            raise RuntimeError('取得間隔制限中。直前の取得は失敗しました')
        return path.read_bytes(), meta
    meta = {'attempt_epoch': time.time(), 'url': DAILY_URL, 'ok': False, 'fetched_at': now.isoformat()}
    atomic_json(meta_path, meta)
    req = urllib.request.Request(DAILY_URL, headers={'User-Agent': 'KeibaTrioResearch/2 (paper analysis; 15min schedule)'})
    with urllib.request.urlopen(req, timeout=45) as response:
        raw = response.read(30_000_001)
        disposition = response.headers.get('Content-Disposition', '')
    read_archive(raw)
    stamp = re.search(r'(\d{8})_(\d{10})_race\.zip', disposition)
    if not stamp:
        raise ValueError('公式配信時刻を確認できません。予想生成を停止')
    meta.update(ok=True, source_date=stamp[1], source_at=datetime.fromtimestamp(int(stamp[2]), timezone.utc).isoformat(), sha256=hashlib.sha256(raw).hexdigest())
    temp = path.with_suffix('.tmp')
    temp.write_bytes(raw)
    temp.replace(path)
    atomic_json(meta_path, meta)
    return raw, meta

def load_model(state):
    """Only the project's trusted private-state artifact, verified before unpickling."""
    path, mp = state / 'model.pkl', state / 'model_meta.json'
    if not path.exists() or not mp.exists():
        raise ValueError('学習済みモデルが未配置。予想は生成しません')
    meta = json.loads(mp.read_text())
    if hashlib.sha256(path.read_bytes()).hexdigest() != meta['sha256'] or meta['schema'] != SCHEMA:
        raise ValueError('モデルのチェックサム・入力スキーマが不一致')
    with path.open('rb') as f:
        bundle = pickle.load(f)
    if bundle.get('feature_schema') != SCHEMA or bundle.get('version') != meta['version']:
        raise ValueError('モデル版が不一致')
    return bundle, meta

def snapshot_prediction(bundle, horses, race, meta, now):
    clean, context = allowlisted(horses, race)
    with threadpool_limits(limits=1):
        output = trio_model.predict_entries(bundle, clean, context)
    if output['status'] != 'research_only':
        raise ValueError(output['status'])
    by_number = {int(h['馬番']): h for h in horses}
    for h in output['horses']:
        h['reasons'] = evidence(by_number[h['number']])
        h['concerns'] = concerns(by_number[h['number']])
        pop = str(by_number[h['number']].get('人気', '')).strip()
        h['observed_popularity'] = int(pop) if pop.isdigit() and int(pop) > 0 else None
    # Popularity is an observation from the timestamped DAILY pre-race file only.
    # It never enters the score model or changes fixed ticket construction.
    outsiders = []
    for h in output['horses'][:5]:
        cs = record_counts(by_number[h['number']].get('全成績', ''))
        if h['observed_popularity'] and h['observed_popularity'] >= 6 and cs and sum(cs) >= 5 and sum(cs[:3])/sum(cs) >= .3:
            outsiders.append({'number':h['number'], 'name':h['name'], 'observed_popularity':h['observed_popularity'],
                'reason':'観測時6人気以下・モデル上位5頭・過去5走以上で累積3着内率30%以上。探索仮説であり収益優位性は未検証'})
    strategies = {}
    scores = [h['model_score'] for h in output['horses']]
    numbers = [h['number'] for h in output['horses']]
    for name, unit in [('axis6', 500), ('box10', 300)]:
        ts = trio_model.picks(numbers, scores, name)
        strategies[name] = {'tickets': ts, 'unit': unit, 'stake': unit * len(ts)}
    return {'date': now.astimezone(JST).date().isoformat(), 'track': race['競馬場'], 'race': int(race['レース番号']),
        'time': start_time(race).strftime('%H:%M'), 'scheduled_start': start_time(race).isoformat(),
        'model_version': bundle['version'], 'model_sha256': meta['model_sha256'], 'schema': SCHEMA,
        'input_sha256': digest({'horses': clean, 'race': context}), 'source_sha256': meta['sha256'],
        'source_at': meta['source_at'], 'fetched_at': meta['fetched_at'], 'fixed_at': now.isoformat(),
        'horses': output['horses'], 'strategies': strategies, 'probabilities_calibrated': False,
        'outsider_candidates': outsiders, 'outsider_status': '当日配信の人気を取得時点の観測として保存。穴条件は探索仮説。三連複オッズ・期待値は未検証',
        'research_baskets': baskets(numbers, clean, {h['number']: h['observed_popularity'] for h in output['horses'] if h['observed_popularity']}),
        'research_basket_version': BASKET_VERSION, 'research_rules_sha256': RULE_SHA256,
        'research_budget': BUDGET, 'research_popularity_status': '公式当日配信を固定時に観測。確定人気の遡及利用なし',
        'research_observation_sha256': digest({'popularity': {h['number']: h['observed_popularity'] for h in output['horses']}, 'source_sha256': meta['sha256']}),
        'decision': '研究記録のみ。収益性未確認につき実購入は推奨しない',
        'paper_only': True}

def skip_reason(horses, race, now, meta):
    if not horses or len(horses) < 5:
        return '出走馬が5頭未満、または出馬表不足'
    remaining = (start_time(race) - now).total_seconds()
    if remaining <= 300:
        return '発走5分前の固定期限を過ぎています。遡って予想を作りません'
    if remaining > 3600:
        return '発走60分前まで待機。直前に利用できる入力を待ちます'
    if any(str(h.get('着順', '')).strip() for h in horses):
        return '発走前データに着順が混在。新規予想を停止'
    if any(not str(h.get('馬名', '')).strip() or h['馬名'].strip() == '0-' for h in horses):
        return '馬名の取得不良'
    if any(not str(h.get('馬体重', '')).strip().isdigit() for h in horses):
        return '馬体重未発表・欠損。学習時との入力差を避けて待機'
    if any(record_counts(h.get('全成績', '')) is None for h in horses):
        return '全成績の欠損・形式不正'
    return None

def process(state, raw, meta, bundle, model_meta, now):
    data = read_archive(raw)
    races, horses, paybacks = indexed(data)
    today = now.astimezone(JST).strftime('%Y%m%d')
    if meta.get('source_date') != today or any(r['競走年月日'] != today for r in data['racelist']):
        raise ValueError('公式配信の日付が今日と一致しません')
    age = (now - datetime.fromisoformat(meta['source_at'])).total_seconds()
    if not -60 <= age <= 600:
        raise ValueError('公式データが10分以上古いか未来時刻です')
    atomic_json(state/'racecards.json', {'date':now.astimezone(JST).date().isoformat(),'races':[{'date':now.astimezone(JST).date().isoformat(),'track':r['競馬場'],'race':int(r['レース番号']),'race_name':r.get('レース名',''),'time':start_time(r).strftime('%H:%M'),'scheduled_start':start_time(r).isoformat(),'source_at':meta['source_at']} for r in races.values() if r['競馬場'] not in EXCLUDED]})
    ledger = Ledger(state / 'ledger.jsonl')
    fixed = ledger.latest('prediction')
    observations = ledger.latest('observation')
    results = ledger.latest('result')
    for k, race in sorted(races.items(), key=lambda item: (start_time(item[1]), item[0])):
        if race['競馬場'] in EXCLUDED:
            continue
        hs = horses.get(k, [])
        if k not in fixed:
            reason = skip_reason(hs, race, now, meta)
            if reason:
                payload = {'date': now.astimezone(JST).date().isoformat(), 'track': race['競馬場'], 'race': int(race['レース番号']),
                    'time': start_time(race).strftime('%H:%M'), 'reason': reason, 'source_at': meta['source_at']}
                if observations.get(k, {}).get('payload', {}).get('reason') != reason:
                    observations[k] = ledger.append('observation', k, payload, now)
                continue
            prediction = snapshot_prediction(bundle, hs, race, {**meta, 'model_sha256': model_meta['sha256']}, now)
            fixed[k] = ledger.append('prediction', k, prediction, now)
        if skip_reason(hs,race,now,meta) is None:
            trifecta_live.freeze(state,ledger,k,hs,race,meta,now)
        pred = fixed[k]['payload']
        if now < datetime.fromisoformat(pred['scheduled_start']) + timedelta(minutes=3):
            continue
        result = settle(pred, hs, paybacks.get(k, []))
        result.update(source_sha256=meta['sha256'], source_at=meta['source_at'], source_url=DAILY_URL)
        old = results.get(k)
        # Append corrections as new events; never edit frozen tickets or earlier results.
        comparison = lambda value: {a: b for a, b in value.items() if a not in ('source_sha256', 'source_at')}
        if not old or comparison(old['payload']) != comparison(result):
            results[k] = ledger.append('result', k, result, now)
    trifecta_live.reconcile(ledger,horses,paybacks,meta,now)
    return ledger

def public_data(state, now, health):
    ledger = Ledger(state / 'ledger.jsonl')
    predictions, results, observations = ledger.latest('prediction'), ledger.latest('result'), ledger.latest('observation')
    rows = []
    for k, e in predictions.items():
        p = e['payload'].copy()
        result = results.get(k)
        p.update(race_key=k, commitment=e['hash'], result=result['payload'] if result else {'status': 'pending', 'reason': '公式結果待ち'},
                 result_updated_at=result['recorded_at'] if result else None)
        rows.append(p)
    rows.sort(key=lambda r: (r['scheduled_start'], r['track'], r['race']), reverse=True)
    summary = {}
    for name in ('axis6', 'box10'):
        eligible = [r['result']['strategies'][name] for r in rows if r['result']['status'] == 'settled']
        stake, payout = sum(r['stake'] for r in eligible), sum(r['payout'] for r in eligible)
        summary[name] = {'races': len(eligible), 'hits': sum(r['hit'] for r in eligible), 'stake': stake, 'payout': payout,
            'roi_pct': payout / stake * 100 if stake else None, 'hit_rate': sum(r['hit'] for r in eligible) / len(eligible) if eligible else None}
        summary[name]['risk'] = summarize([{'scheduled_start': p['scheduled_start'], 'track': p['track'], 'race': p['race'],
            'stake': p['strategies'][name]['stake'], 'ticket_count': len(p['strategies'][name]['tickets']),
            'decision': 'paper_buy', 'status': p['result']['status'],
            **p['result'].get('strategies', {}).get(name, {})} for p in rows])
    today = now.astimezone(JST).date().isoformat()
    tri=trifecta_live.public(ledger)
    cards=json.loads((state/'racecards.json').read_text()) if (state/'racecards.json').exists() else {}
    cards=cards.get('races',[]) if cards.get('date')==today else []
    basket_rows = []
    for p in rows:
        for name, bet in p.get('research_baskets', {}).items():
            result = p['result'].get('research_baskets', {}).get(name, {})
            basket_rows.append({'strategy': name, 'scheduled_start': p['scheduled_start'], 'track': p['track'], 'race': p['race'],
                'stake': bet['stake'], 'ticket_count': len(bet['tickets']), 'decision': bet['decision'],
                'status': p['result']['status'] if result else 'pending', **result})
    research_summary = {name: summarize([r for r in basket_rows if r['strategy'] == name]) for name in sorted({r['strategy'] for r in basket_rows})}
    skips = [dict(e['payload'], recorded_at=e['recorded_at']) for k, e in observations.items() if k not in predictions and e['payload']['date'] == today]
    # Old-day unresolved forecasts are retained; no zero-pick fallback to yesterday.
    return ({'schema_version': 2, 'date': today, 'trifecta':tri, 'racecards':cards, 'generated_at': now.isoformat(), 'health': health,
        'races': [r for r in rows if r['date'] == today], 'skips': skips, 'summary': summary,
        'ledger_head': ledger.events[-1]['hash'] if ledger.events else None, 'paper_only': True,
        'research_summary': research_summary, 'research_basket_version': BASKET_VERSION,
        'jra_status': '中央は対象区分を維持。今回の接続・数値評価は地方のみ。中央の予想は未接続'},
        {'schema_version': 2, 'generated_at': now.isoformat(), 'races': rows, 'trifecta':tri,
         'changes': [dict({k: e[k] for k in ('seq', 'kind', 'race_key', 'recorded_at', 'hash', 'previous')},
             reason=e['payload'].get('reason'), result=e['payload'] if e['kind']=='result' else None) for e in ledger.events],
         'summary': summary, 'paper_only': True, 'research_summary': research_summary,
         'research_basket_version': BASKET_VERSION})

def backfill(state, now):
    """Reconcile unresolved days and recheck settled records for 7 days, one download/month/day.

    Monthly raw data stays private. Last month's final file is fetched after rollover.
    """
    ledger = Ledger(state / 'ledger.jsonl')
    results = ledger.latest('result')
    pending = {k: e for k, e in ledger.latest('prediction').items()
        if datetime.fromisoformat(e['payload']['scheduled_start']).date() < now.astimezone(JST).date()
        and (results.get(k, {}).get('payload', {}).get('status') != 'settled'
            or datetime.fromisoformat(e['payload']['scheduled_start']).date() >= now.astimezone(JST).date()-timedelta(days=7))}
    tri_pending={k:e for k,e in ledger.latest('trifecta_prediction').items() if datetime.fromisoformat(e['payload']['scheduled_start']).date()<now.astimezone(JST).date() and ledger.latest('trifecta_result').get(k,{}).get('payload',{}).get('status')!='settled'}
    for month in sorted({k[:6] for k in pending}|{k[:6] for k in tri_pending}):
        path = state / 'monthly' / (month + '.zip')
        mp = path.with_suffix('.json')
        info = json.loads(mp.read_text()) if mp.exists() else {}
        day = now.astimezone(JST).date().isoformat()
        if info.get('attempt_day') != day:
            atomic_json(mp, {'attempt_day': day, 'ok': False})
            url = f'https://www.keiba.go.jp/KeibaWeb/DataDownload/RaceDataDownload?k_month={int(month[4:])}&k_year={month[:4]}&type=monthly'
            with urllib.request.urlopen(url, timeout=45) as response:
                raw = response.read(30_000_001)
                disposition = response.headers.get('Content-Disposition', '')
            read_archive(raw)
            stamp = re.search(r'(\d{6})_(\d{10})_race\.zip', disposition)
            if not stamp or stamp[1] != month:
                raise ValueError('月次公式ファイルの日付・配信時刻を確認できません')
            path.write_bytes(raw)
            info = {'attempt_day': day, 'ok': True, 'sha256': hashlib.sha256(raw).hexdigest(),
                'fetched_at': now.isoformat(), 'source_at': datetime.fromtimestamp(int(stamp[2]), timezone.utc).isoformat()}
            atomic_json(mp, info)
        if not path.exists() or not info.get('ok'):
            raise ValueError('月次補完の取得失敗。次の取得可能日まで照合保留')
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != info['sha256']:
            raise ValueError('月次原本のチェックサムが不一致')
        _, horses, paybacks = indexed(read_archive(raw))
        horses={k:enrich(state,k,hs) for k,hs in horses.items()}
        trifecta_live.reconcile(ledger,horses,paybacks,info,now)
        for k, event in pending.items():
            if not k.startswith(month) or k not in horses:
                continue
            result = settle(event['payload'], horses[k], paybacks.get(k, []))
            result['finish_status_sources']=[h['status_source'] for h in horses[k] if 'status_source' in h]
            result.update(source_sha256=hashlib.sha256(raw).hexdigest(), source_at=info['source_at'], fetched_at=info['fetched_at'], source_kind='monthly_backfill',
                source_url=f'https://www.keiba.go.jp/KeibaWeb/DataDownload/RaceDataDownload?k_month={int(month[4:])}&k_year={month[:4]}&type=monthly')
            old = results.get(k, {}).get('payload', {})
            core = lambda value: {a:b for a,b in value.items() if a not in ('source_sha256','source_at','fetched_at','source_kind')}
            if core(old) != core(result):
                ledger.append('result', k, result, now)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.state.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    health = {'status': 'ok', 'checked_at': now.isoformat(), 'pipeline_version': VERSION, 'run_id': os.environ.get('GITHUB_RUN_ID'),
        'engine_commit': os.environ.get('RESEARCH_ENGINE_COMMIT')}
    health['stages'] = {}
    failed = False
    try:
        raw, meta = fetch_daily(args.state, now)
        health.update(source_at=meta['source_at'], fetched_at=meta['fetched_at'], source_sha256=meta['sha256'])
        bundle, model_meta = load_model(args.state)
        process(args.state, raw, meta, bundle, model_meta, datetime.now(timezone.utc))
        health.update(model_version=bundle['version'])
        health['stages']['daily'] = {'status': 'ok'}
    except Exception as e:
        failed = True
        health.update(status='error', error=type(e).__name__ + ': ' + str(e))
        health['stages']['daily'] = {'status': 'error', 'error': health['error']}
    # Past results must not depend on today's feed freshness or model readiness.
    # This never generates new predictions and never changes their frozen payloads.
    try:
        backfill(args.state, now)
        health['stages']['reconciliation'] = {'status': 'ok'}
    except Exception as e:
        failed = True
        message = type(e).__name__ + ': ' + str(e)
        health['stages']['reconciliation'] = {'status': 'error', 'error': message}
        health.update(status='error', error=health.get('error', '') + ('; ' if health.get('error') else '') + message)
    # Integrity failure propagates instead of overwriting a valid public history.
    latest, history = public_data(args.state, now, health)
    atomic_json(args.out / 'latest.json', latest)
    atomic_json(args.out / 'history.json', history)
    atomic_json(args.out / 'health.json', health)
    print(canonical({'status': health['status'], 'date': latest['date'], 'predictions_today': len(latest['races']), 'skips': len(latest['skips'])}))
    return 1 if failed else 0

if __name__ == '__main__':
    raise SystemExit(main())
