import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from research.strategies import baskets, BUDGET
from research.metrics import summarize
from research.live import main, snapshot_prediction
from research.domain import settle, Ledger
from test_research import horses, RACE, NOW, BUNDLE, META, finished, payouts

class StrategyTests(unittest.TestCase):
    def test_all_baskets_share_budget_with_legal_units(self):
        hs = horses(); hs[-1]['全成績'] = '1-2-1-6'; hs[-1]['うち当距離成績'] = '1-1-1-2'
        hs[0]['うち当距離成績'] = '1-2-2-3'; hs[0]['全成績'] = '3-3-2-2'
        bs = baskets(list(range(1, 7)), hs, {i:i for i in range(1, 7)})
        self.assertEqual([len(bs[k]['tickets']) for k in ('box4', 'box10', 'axis6', 'two_axis4')], [4,10,6,4])
        for b in bs.values():
            if b['tickets']:
                self.assertEqual(b['stake'], BUDGET); self.assertEqual(b['unit'] % 100, 0)
                self.assertEqual(len(b['tickets']),len(set(b['tickets'])))
        self.assertEqual(bs['outsider6']['outsider'],6)
        self.assertTrue(any(6 in t for t in bs['outsider6']['tickets']))
    def test_missing_popularity_cannot_become_a_final_odds_proxy(self):
        bs = baskets(list(range(1,7)), horses(), {})
        self.assertEqual(bs['popularity_box4']['decision'],'unavailable')
        self.assertEqual(bs['outsider6']['decision'],'unavailable')
    def test_unqualified_outsider_not_selected_just_for_popularity(self):
        hs = horses(); hs[-1]['うち当距離成績'] = '0-0-0-8'
        bs = baskets(list(range(1,7)), hs, {i:i for i in range(1,7)})
        self.assertEqual(bs['outsider6']['stake'],0)
    def test_weak_conditions_skip_without_reallocating_budget(self):
        bs = baskets(list(range(1,7)), horses(), {i:i for i in range(1,7)})
        self.assertEqual(bs['selective_axis6']['stake'],0)
        self.assertEqual(bs['axis6']['stake'],6000)
    def test_research_settlement_cannot_rewrite_existing_budgets(self):
        p = snapshot_prediction(BUNDLE,horses(),RACE,META,NOW)
        r = settle(p,finished(),payouts())
        self.assertEqual(r['strategies']['axis6']['stake'],3000)
        self.assertEqual(r['research_baskets']['axis6']['stake'],6000)
        self.assertEqual(r['research_baskets']['axis6']['winning_tickets'],1)
    def test_chronological_metrics_preserve_missing_cost_and_skips(self):
        def row(time, status='settled', payout=0, decision='paper_buy'):
            return {'scheduled_start':time,'status':status,'stake':6000 if decision=='paper_buy' else 0,'payout':payout,'hit':payout>0,'ticket_count':6 if decision=='paper_buy' else 0,'winning_tickets':int(payout>0),'decision':decision}
        rs=[row('2026-10-01T12:00:00+09:00',payout=18000),row('2026-10-01T10:00:00+09:00'),row('2026-10-01T11:00:00+09:00'),row('2026-10-01T13:00:00+09:00','pending'),row('2026-10-01T14:00:00+09:00',decision='skip')]
        m=summarize(rs)
        self.assertEqual(m['settled_races'],3);self.assertEqual(m['unresolved_bought_races'],1)
        self.assertEqual(m['committed_stake'],24000);self.assertEqual(m['settled_stake'],18000)
        self.assertEqual(m['roi_pct'],100);self.assertEqual(m['roi_bounds_pending_pct'],[75,None])
        self.assertEqual(m['max_drawdown_scheduled'],12000);self.assertEqual(m['max_losing_streak_known'],2)
        self.assertAlmostEqual(m['ticket_hit_rate_pct'],100/18)
        self.assertEqual(m['largest_payout_share_pct'],100)
    def test_empty_rates_unknown_not_zero(self):
        m=summarize([])
        self.assertIsNone(m['roi_pct']);self.assertIsNone(m['hit_rate_pct'])
    def test_daily_failure_still_attempts_prior_result_backfill(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            with patch('sys.argv',['live','--state',str(p/'state'),'--out',str(p/'out')]), patch('research.live.fetch_daily',side_effect=ValueError('stale')), patch('research.live.backfill') as reconcile:
                self.assertEqual(main(),1)
                reconcile.assert_called_once()
            health=json.loads((p/'out/health.json').read_text())
            self.assertEqual(health['stages']['daily']['status'],'error')
            self.assertEqual(health['stages']['reconciliation']['status'],'ok')

if __name__ == '__main__':
    unittest.main()
