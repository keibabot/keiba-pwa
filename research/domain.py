"""Strict official CSV boundaries and append-only, hash-linked observations."""
from __future__ import annotations
import csv
import hashlib
import io
import json
import math
import os
import re
import zipfile
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

JST = timezone(timedelta(hours=9))
EXCLUDED = {'門別', '帯広ば', '帯広'}
RECORD_FIELDS = ('全成績', '当競馬場成績', 'うち当距離成績', 'ダート左成績', 'ダート右成績', '騎手成績')
HORSE_INPUTS = ('馬番', '馬名', '齢', '性', '負担重量', '馬体重', '馬体重増減', '枠番', *RECORD_FIELDS)
RACE_INPUTS = ('競走年月日', '競馬場', 'レース番号', '発走時刻', '距離', '回り')
SCHEMA = 'nar-trio-whitelist-v1'

def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)

def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()

def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(canonical(value) + '\n', encoding='utf-8')
    os.replace(tmp, path)

def race_key(row):
    day = str(row['競走年月日'])
    if not re.fullmatch(r'\d{8}', day):
        raise ValueError('invalid official race date')
    return f"{day}|{row['競馬場']}|{int(row['レース番号'])}"

def start_time(race):
    return datetime.strptime(str(race['競走年月日']) + str(race['発走時刻']).zfill(4), '%Y%m%d%H%M').replace(tzinfo=JST)

def read_archive(raw):
    if len(raw) > 30_000_000:
        raise ValueError('archive too large')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if sum(i.file_size for i in archive.infolist()) > 150_000_000:
            raise ValueError('expanded archive too large')
        out = {}
        for kind in ('horselist', 'racelist', 'payback'):
            names = [n for n in archive.namelist() if n.endswith('_' + kind + '.csv')]
            if len(names) != 1:
                raise ValueError('missing or ambiguous ' + kind)
            reader = csv.DictReader(io.StringIO(archive.read(names[0]).decode('utf-8-sig')))
            if not {'競走年月日', '競馬場', 'レース番号'} <= set(reader.fieldnames or []):
                raise ValueError('CSV schema changed')
            out[kind] = list(reader)
        return out

def indexed(data):
    races, horses, payouts = {}, defaultdict(list), defaultdict(list)
    for r in data['racelist']:
        k = race_key(r)
        if k in races:
            raise ValueError('duplicate race key')
        races[k] = r
    for h in data['horselist']:
        horses[race_key(h)].append(h)
    for p in data['payback']:
        payouts[race_key(p)].append(p)
    for hs in horses.values():
        numbers = [int(h['馬番']) for h in hs]
        if len(set(numbers)) != len(numbers) or min(numbers, default=0) <= 0:
            raise ValueError('duplicate or invalid horse number')
    return races, horses, payouts

def allowlisted(horses, race):
    return ([{k: h.get(k, '') for k in HORSE_INPUTS} for h in horses], {k: race.get(k, '') for k in RACE_INPUTS})

def record_counts(text):
    if not re.fullmatch(r'\d+-\d+-\d+-\d+', str(text).strip()):
        return None
    return list(map(int, text.split('-')))

def evidence(h):
    out = []
    for label in ('全成績', '当競馬場成績', 'うち当距離成績', '騎手成績'):
        r = record_counts(h.get(label, ''))
        if r is not None:
            n = sum(r)
            out.append(f'{label}: {n}走中{sum(r[:3])}回3着以内' + ('（少数標本）' if n < 10 else ''))
    return out or ['累積成績が不足しています']

def winners(rows):
    result = {}
    for row in rows:
        vals = [str(row.get('３連複組番馬番' + str(i), '')).strip() for i in (1, 2, 3)]
        amount = str(row.get('３連複払戻金（円）', '')).replace(',', '').strip()
        if not any(vals) and not amount:
            continue
        if not all(re.fullmatch(r'\d+', v) for v in vals) or not amount.isdigit():
            raise ValueError('unsupported refund/special payout')
        ticket = tuple(sorted(map(int, vals)))
        if len(set(ticket)) != 3 or min(ticket) <= 0 or int(amount) <= 0:
            raise ValueError('invalid payout')
        if ticket in result and result[ticket] != int(amount):
            raise ValueError('conflicting duplicate payout')
        result[ticket] = int(amount)
    return result

def settle(prediction, horses, paybacks):
    """Unknown scratches/refunds never become a losing/settled record."""
    current = {int(h['馬番']): h for h in horses}
    expected = {h['number'] for h in prediction['horses']}
    if set(current) != expected:
        return {'status': 'review_required', 'reason': '出走馬の増減。取消・返還の公式照合が必要'}
    finishes = [str(h.get('着順', '')).strip() for h in horses]
    if not paybacks:
        return {'status': 'pending', 'reason': '公式三連複払戻は未取得・未確定'}
    if any(v not in ('中止','除外') and (not re.fullmatch(r'\d+', v) or int(v) < 1) for v in finishes):
        return {'status': 'review_required', 'reason': '着順空欄・取消・除外・中止等。返還を推測せず照合待ち'}
    try:
        paid = winners(paybacks)
    except ValueError as e:
        return {'status': 'review_required', 'reason': str(e)}
    if not paid:
        return {'status': 'pending', 'reason': '公式三連複払戻は未取得・未確定'}
    top = {int(h['馬番']) for h in horses if str(h['着順']).isdigit() and 1 <= int(h['着順']) <= 3}
    if len(top) < 3 or any(not set(t) <= top for t in paid):
        return {'status': 'review_required', 'reason': '着順と払戻組番が不整合'}
    # All dead-heat payout rows must be available; a missing row must not silently settle.
    if len(top) > 3:
        from itertools import combinations
        lower = {int(h['馬番']) for h in horses if str(h['着順']).isdigit() and int(h['着順']) < 3}
        expected_winners = {tuple(sorted(t)) for t in combinations(top, 3) if lower <= set(t)}
        if set(paid) != expected_winners:
            return {'status': 'review_required', 'reason': '同着払戻行の完全性を確認できません'}
    scratched={int(h['馬番']) for h in horses if h.get('着順')=='除外'}
    strategies = {}
    for name, bet in prediction['strategies'].items():
        ts = {tuple(sorted(t)) for t in bet['tickets']}
        if len(ts) != len(bet['tickets']):
            raise ValueError('duplicate frozen tickets')
        payout = sum(paid.get(t, 0) for t in ts if not set(t)&scratched) * bet['unit'] // 100
        strategies[name] = {'stake': len(ts) * bet['unit'], 'payout': payout, 'hit': any(t in paid for t in ts), 'refund': sum(bool(set(t)&scratched) for t in ts)*bet['unit'],
            'winning_tickets': sum(t in paid for t in ts), 'ticket_count': len(ts)}
    result = {'status': 'settled', 'strategies': strategies, 'dead_heat': len(paid) > 1,
        'finish': [{'number': int(h['馬番']), 'position': int(h['着順']) if str(h['着順']).isdigit() else None,'status':h['着順']} for h in sorted(horses, key=lambda h: (int(h['着順']) if str(h['着順']).isdigit() else 999, int(h['馬番'])))],
        'official_trio_paybacks': [{'numbers': list(t), 'payback_100': amount} for t, amount in sorted(paid.items())],
        'reason': '公式着順・三連複払戻を照合'}
    from research.trifecta import payouts
    try:
        result['official_trifecta_paybacks']=[{'numbers':list(t),'payback_100':v} for t,v in payouts(paybacks).items()]
    except ValueError:
        result['official_trifecta_paybacks']=None
    if 'research_baskets' in prediction:
        result['research_baskets'] = {}
        for name, bet in prediction['research_baskets'].items():
            ts = {tuple(sorted(t)) for t in bet['tickets']}
            if len(ts) != len(bet['tickets']) or (ts and (bet['unit'] <= 0 or bet['unit'] % 100)):
                raise ValueError('invalid frozen research basket')
            if any(len(t) != 3 or len(set(t)) != 3 or not set(t) <= expected for t in ts):
                raise ValueError('invalid research ticket')
            result['research_baskets'][name] = {'stake': len(ts) * bet['unit'],
                'payout': sum(paid.get(t, 0) for t in ts if not set(t)&scratched) * bet['unit'] // 100,
                'hit': any(t in paid for t in ts), 'refund': sum(bool(set(t)&scratched) for t in ts)*bet['unit'],
                'winning_tickets': sum(t in paid for t in ts), 'ticket_count': len(ts),
                'decision': bet['decision']}
    return result

class Ledger:
    def __init__(self, path):
        self.path = Path(path)
        self.events = []
        previous = '0' * 64
        if self.path.exists():
            for line in self.path.read_text(encoding='utf-8').splitlines():
                event = json.loads(line)
                hashed = event.pop('hash')
                if event.get('previous') != previous or digest(event) != hashed:
                    raise ValueError('ledger integrity failure')
                event['hash'] = hashed
                self.events.append(event)
                previous = hashed

    def append(self, kind, key, payload, at):
        event = {'seq': len(self.events) + 1, 'previous': self.events[-1]['hash'] if self.events else '0' * 64,
                 'kind': kind, 'race_key': key, 'recorded_at': at.isoformat(), 'payload': payload}
        # Freeze nested values and normalize JSON object keys before computing the commitment.
        event = json.loads(canonical(event))
        event['hash'] = digest(event)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open('a', encoding='utf-8') as f:
            f.write(canonical(event) + '\n')
            f.flush()
            os.fsync(f.fileno())
        self.events.append(event)
        return event

    def latest(self, kind):
        return {e['race_key']: e for e in self.events if e['kind'] == kind}
