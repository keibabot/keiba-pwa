import copy,hashlib,json,pickle,tempfile,unittest
from pathlib import Path
from datetime import timedelta
from unittest.mock import patch
import numpy as np
from test_research import horses,RACE,META,NOW,finished,payouts
from research.domain import Ledger,settle
from research.trifecta import payouts as ordered_payouts,VERSION
from research.trifecta_live import freeze,settle_ordered

class PositionModel:
    classes_=np.array([0,1,2,3])
    def predict_proba(self,X):
        p=np.linspace(.7,.2,len(X));return np.column_stack([p,p,p[::-1],np.roll(p,1)])
class TrifectaTests(unittest.TestCase):
    def test_ledger_normalizes_integer_keys_and_freezes_nested_payload(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'ledger.jsonl';l=Ledger(path);p={'ranks':{1:[1,2,3],10:[3,2,1]}}
            event=l.append('test','key',p,NOW);p['ranks'][1][0]=999
            loaded=Ledger(path);self.assertEqual(loaded.events[0],event);self.assertEqual(event['payload']['ranks']['1'][0],1)
    def test_order_and_duplicate_official_payout(self):
        p={'３連単組番馬番1':'3','３連単組番馬番2':'1','３連単組番馬番3':'2','３連単払戻金（円）':'12,300'}
        self.assertEqual(ordered_payouts([p,p]),{(3,1,2):12300})
        with self.assertRaises(ValueError):ordered_payouts([p,dict(p,**{'３連単払戻金（円）':'12000'})])
    def test_frozen_predictions_once_and_never_after_cutoff(self):
        with tempfile.TemporaryDirectory() as d:
            state=Path(d);raw=pickle.dumps({'model':PositionModel()});(state/'trifecta_model.pkl').write_bytes(raw);(state/'trifecta_model_meta.json').write_text(json.dumps({'sha256':hashlib.sha256(raw).hexdigest(),'version':VERSION}))
            l=Ledger(state/'ledger.jsonl');freeze(state,l,'key',horses(12),RACE,META,NOW)
            first=l.latest('trifecta_prediction')['key'];self.assertLessEqual(first['payload']['stake'],1200)
            self.assertEqual(Ledger(state/'ledger.jsonl').latest('trifecta_prediction')['key'],json.loads(json.dumps(first)))
            changed=horses(12);changed[0]['全成績']='0-0-0-99';freeze(state,l,'key',changed,RACE,META,NOW)
            self.assertEqual(l.latest('trifecta_prediction')['key'],first);self.assertEqual(len(l.events),1)
            freeze(state,l,'late',changed,RACE,META,NOW+timedelta(minutes=29));self.assertNotIn('late',l.latest('trifecta_prediction'))
    def test_dnf_known_is_not_refund_unknown_blank_still_held(self):
        from test_research import frozen
        hs=finished();hs[-1]['着順']='中止';self.assertEqual(settle(frozen(),hs,payouts())['status'],'settled')
        hs[-1]['着順']='';self.assertEqual(settle(frozen(),hs,payouts())['status'],'review_required')
    def test_official_excluded_horse_refunds_only_containing_tickets(self):
        from test_research import frozen
        p=frozen();hs=finished();hs[4]['着順']='除外'
        result=settle(p,hs,payouts());self.assertEqual(result['status'],'settled')
        self.assertEqual(result['strategies']['axis6']['refund'],1500)
        self.assertEqual(result['strategies']['axis6']['payout'],6150)
    def test_ordered_settlement_and_dead_heat_completeness(self):
        p={'horses':[{'number':i} for i in range(1,7)],'tickets':[[1,2,3]],'all_races_tickets':[[1,2,3]],'unit':100}
        ps=[{'３連単組番馬番1':'1','３連単組番馬番2':'2','３連単組番馬番3':'3','３連単払戻金（円）':'1230'}]
        self.assertEqual(settle_ordered(p,finished(),ps)['strategies']['selected']['payout'],1230)
        hs=finished();hs[3]['着順']='3';self.assertEqual(settle_ordered(p,hs,ps)['status'],'review_required')
        ps.append(dict(ps[0],**{'３連単組番馬番3':'4','３連単払戻金（円）':'850'}));self.assertEqual(settle_ordered(p,hs,ps)['status'],'settled')
    def test_publication_401_retains_payload_and_records_actionable_error(self):
        import os,urllib.error
        from datetime import datetime,timezone
        from research.publish import main
        cwd=Path.cwd()
        with tempfile.TemporaryDirectory() as d:
            os.chdir(d)
            try:
                Path('health.json').write_text(json.dumps({'checked_at':datetime.now(timezone.utc).isoformat(),'run_id':'test'}));Path('history.json').write_text('immutable test')
                with patch.dict(os.environ,{'PWA_REPO_TOKEN':'test-only-not-a-real-token','GITHUB_RUN_ID':'test'}),patch('urllib.request.urlopen',side_effect=urllib.error.HTTPError('https://api.github.com',401,'Unauthorized',{},None)):
                    with self.assertRaisesRegex(RuntimeError,'authentication_failed'):main()
                self.assertEqual(Path('history.json').read_text(),'immutable test');self.assertEqual(json.loads(Path('publication_status.json').read_text())['http_status'],401)
            finally:os.chdir(cwd)
