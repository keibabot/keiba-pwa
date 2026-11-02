"""Versioned, predeclared research baskets; never a recommendation.

Only observed pre-start popularity is legal in live use. Monthly popularity is
final and may be passed ONLY by the explicitly retrospective reference study.
"""
from itertools import combinations
from research.domain import record_counts, digest

VERSION = 'trio-baskets-v1'
BUDGET = 6000
RULES = {
    'axis6': 'モデル1位軸＋2〜5位へ6点',
    'box4': 'モデル上位4頭BOX・4点',
    'box10': 'モデル上位5頭BOX・10点',
    'two_axis4': 'モデル上位2頭軸＋3〜6位へ4点',
    'outsider6': '6人気以下・モデル6位以内・全成績5走以上3着内率30%以上・距離成績3走以上3着内率30%以上の最上位馬を相手に確保。いなければ見送り',
    'selective_axis6': '軸の全成績10走以上3着内率50%以上、距離成績5走以上3着内率30%以上の場合だけ軸6点',
    'popularity_box4': '観測時人気上位4頭BOX・4点（月次再現では確定人気による参考分析）',
}
RULE_SHA256 = digest({'version': VERSION, 'budget': BUDGET, 'rules': RULES})

def rate(horse, field, minimum, threshold):
    cs = record_counts(horse.get(field, ''))
    return bool(cs and sum(cs) >= minimum and sum(cs[:3]) / sum(cs) >= threshold)

def concerns(horse):
    reasons = []
    for field in ('全成績', '当競馬場成績', 'うち当距離成績'):
        cs = record_counts(horse.get(field, ''))
        if cs is None or sum(cs) < 5:
            reasons.append(f'{field}は欠損または5走未満')
        elif sum(cs[:3]) / sum(cs) < .3:
            reasons.append(f'{field}の過去3着内率は30%未満')
    return reasons + ['近走の着差・相手関係・展開・調教は今回のモデルで未評価', '順位スコアは的中確率・期待値ではありません']

def baskets(ranked_numbers, horses, popularity):
    """Inputs must be timestamped in the caller. Never accepts outcomes or payouts."""
    ns = list(ranked_numbers)
    by = {int(h['馬番']): h for h in horses}
    if len(ns) < 6 or len(set(ns)) != len(ns) or set(ns) != set(by):
        return {k: pack([], '6頭以上の完全な出馬表が必要', unavailable=True) for k in RULES}
    axis = lambda opponents: [(ns[0], *pair) for pair in combinations(opponents, 2)]
    result = {'axis6': pack(axis(ns[1:5])), 'box4': pack(combinations(ns[:4], 3)),
              'box10': pack(combinations(ns[:5], 3)),
              'two_axis4': pack([(ns[0], ns[1], n) for n in ns[2:6]])}
    popularity_complete = len(popularity) == len(ns) and set(popularity) == set(ns) and all(type(v) is int and v > 0 for v in popularity.values()) and len(set(popularity.values())) == len(ns)
    candidates = [n for n in ns[:6] if popularity.get(n, 0) >= 6
                  and rate(by[n], '全成績', 5, .3) and rate(by[n], 'うち当距離成績', 3, .3)]
    opponents = ns[1:5]
    outsider = next((n for n in candidates if n != ns[0]), None)
    if not popularity_complete:
        result['outsider6'] = pack([], '人気が全馬分揃わず穴条件は判定不能', unavailable=True)
    elif outsider is not None:
        if outsider not in opponents:
            opponents = ns[1:4] + [outsider]
        result['outsider6'] = dict(pack(axis(opponents)), outsider=outsider,
                                  reasons=['人気薄だけでなく全成績と距離実績の条件を満たす'],
                                  concerns=concerns(by[outsider]))
    else:
        result['outsider6'] = pack([], '根拠条件を満たす穴の相手候補なし・人気未取得を含む')
    qualifies = rate(by[ns[0]], '全成績', 10, .5) and rate(by[ns[0]], 'うち当距離成績', 5, .3)
    result['selective_axis6'] = pack(axis(ns[1:5]) if qualifies else [],
                                     None if qualifies else '軸の全成績・距離成績が事前定義した条件に届かない')
    if popularity_complete:
        popular = sorted(ns, key=lambda n: (popularity[n], n))
        result['popularity_box4'] = pack(combinations(popular[:4], 3))
    else:
        result['popularity_box4'] = pack([], '人気を全馬分確認できないため基準を作れない', unavailable=True)
    return result

def pack(tickets, reason=None, unavailable=False):
    ts = sorted({tuple(sorted(t)) for t in tickets})
    if any(len(t) != 3 or len(set(t)) != 3 or min(t) < 1 for t in ts):
        raise ValueError('invalid triple')
    if ts and BUDGET % (len(ts) * 100):
        raise ValueError('equal budget must use 100-yen units')
    unit = BUDGET // len(ts) if ts else 0
    return {'tickets': ts, 'unit': unit, 'stake': unit * len(ts), 'budget': BUDGET,
            'decision': 'unavailable' if unavailable else 'paper_buy' if ts else 'skip',
            'reason': reason or '事前定義の比較用買い目。実購入・購入推奨なし'}
