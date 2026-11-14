"""All outcomes retained; race rates, ticket rates and capital at risk separated."""
from collections import defaultdict
import numpy as np
from research.audit import interval

def summarize(rows):
    ordered = sorted(rows, key=lambda r: (r['scheduled_start'], r.get('track', ''), int(r.get('race', 0))))
    bought = [r for r in ordered if r.get('stake', 0) > 0]
    settled = [r for r in bought if r.get('status') == 'settled']
    stake = sum(r['stake'] for r in settled)
    payout = sum(r['payout'] for r in settled)
    refund = sum(r.get('refund', 0) for r in settled)
    hits = sum(bool(r['hit']) for r in settled)
    tickets = sum(r.get('ticket_count', 0) for r in settled)
    winning = sum(r['winning_tickets'] for r in settled) if settled and all(r.get('winning_tickets') is not None for r in settled) else None
    balance = peak = drawdown = run = longest = 0
    for r in ordered:
        if r.get('stake', 0) > 0 and r.get('status') == 'settled':
            balance += r['payout'] + r.get('refund', 0) - r['stake']
            peak = max(peak, balance); drawdown = max(drawdown, peak - balance)
            run = 0 if r['hit'] else run + 1
            longest = max(longest, run)
        elif r.get('stake', 0):
            run = 0  # An unresolved result breaks the known consecutive sequence.
    amounts = sorted((r['payout'] for r in settled), reverse=True)
    days = defaultdict(lambda: [0, 0])
    for r in settled:
        days[r['scheduled_start'][:10]][0] += r['stake']
        days[r['scheduled_start'][:10]][1] += r['payout'] + r.get('refund', 0)
    roi_interval = None
    if len(days) > 1:
        a = np.array(list(days.values()), dtype=float)
        sampled = a[np.random.default_rng(20261102).integers(0, len(a), (1000, len(a)))].sum(axis=1)
        roi_interval = np.quantile(100 * sampled[:, 1] / sampled[:, 0], [.025, .975]).tolist()
    total_committed = sum(r['stake'] for r in bought)
    return {'target_races': len(rows), 'bought_races': len(bought), 'settled_races': len(settled),
            'skip_races': sum(r.get('decision') == 'skip' for r in rows),
            'unavailable_races': sum(r.get('decision') == 'unavailable' for r in rows),
            'unresolved_bought_races': len(bought) - len(settled),
            'skip_rate_pct': 100 * sum(r.get('decision') == 'skip' for r in rows) / len(rows) if rows else None,
            'hits': hits, 'hit_rate_pct': 100 * hits / len(settled) if settled else None,
            'hit_wilson95_pct': interval(hits, len(settled)),
            'ticket_count': tickets, 'winning_tickets': winning,
            'average_points':sum(r.get('ticket_count',0) for r in bought)/len(bought) if bought else None,
            'ticket_hit_rate_pct': 100 * winning / tickets if tickets and winning is not None else None,
            'committed_stake': total_committed, 'settled_stake': stake, 'payout': payout, 'refund': refund,
            'roi_pct': 100 * (payout + refund) / stake if stake else None,
            'roi_day_bootstrap95_pct': roi_interval,
            'profit': payout + refund - stake, 'actual_purchase': False, 'fees': None,
            'roi_bounds_pending_pct': [100 * (payout + refund) / total_committed, None] if total_committed else None,
            'roi_without_largest_payout_pct': 100 * (payout + refund - max(amounts, default=0)) / stake if stake else None,
            'largest_payout_share_pct': 100 * max(amounts, default=0) / payout if payout else None,
            'top3_payout_share_pct': 100 * sum(amounts[:3]) / payout if payout else None,
            'max_losing_streak_known': longest, 'max_drawdown_scheduled': drawdown,
            'order_status': '予定発走時刻順。同時刻は場名・数値R順。実発走時刻は未取得。未確定を含むDDは確定分のみの暫定値',
            'refund_policy': '払戻と返還を分離し回収率の分子に合算。返還額不明は要照合として投資額と未確定数を保持'}
