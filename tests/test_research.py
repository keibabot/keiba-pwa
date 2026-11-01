import copy
import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
import numpy as np
from research.domain import Ledger, digest, settle, winners, indexed, read_archive, SCHEMA
from research.live import process, snapshot_prediction, skip_reason, public_data
import trio_model

NOW=datetime(2026,11,1,4,0,tzinfo=timezone.utc)
RACE={'競走年月日':'20261101','競馬場':'盛岡','レース番号':'2','発走時刻':'1330','距離':'1200','回り':'左'}
def horses(n=6):
 return [{'馬番':str(i),'馬名':f'Test{i}','齢':'4','性':'牡','負担重量':'56','馬体重':'480','馬体重増減':'0','枠番':str(i),'全成績':'1-2-1-6','当競馬場成績':'1-0-0-2','うち当距離成績':'0-0-1-2','騎手成績':'0-1-0-2','ダート左成績':'1-2-1-6','ダート右成績':'0-0-0-0','着順':'','人気':str(i)} for i in range(1,n+1)]
class Model:
 def predict_proba(self,X):
  p=np.linspace(.7,.2,len(X));return np.column_stack([1-p,p])
BUNDLE={'model':Model(),'version':'test-only','strategy':'axis6','feature_schema':SCHEMA}
META={'source_date':'20261101','source_at':NOW.isoformat(),'fetched_at':NOW.isoformat(),'sha256':'a'*64,'model_sha256':'b'*64}
def frozen():return snapshot_prediction(BUNDLE,horses(),RACE,META,NOW)
def payouts():return [{'３連複組番馬番1':'1','３連複組番馬番2':'2','３連複組番馬番3':'3','３連複払戻金（円）':'1230'}]
def finished():
 hs=horses()
 for i,h in enumerate(hs,1):h['着順']=str(i)
 return hs
class DomainTests(unittest.TestCase):
 def test_model_inputs_ignore_postrace_columns(self):
  a=trio_model.features(horses(),RACE)
  hs=horses()
  for h in hs:h.update(着順='1',人気='99',タイム='9999',払戻='99999',オッズ='99999')
  r=dict(RACE,上がり3F='1',ハロンタイム1='9999')
  np.testing.assert_equal(a,trio_model.features(hs,r))
 def test_equal_budgets_and_unique_tickets(self):
  p=frozen()
  self.assertEqual([s['stake'] for s in p['strategies'].values()],[3000,3000])
  for b in p['strategies'].values():self.assertEqual(len(b['tickets']),len({tuple(t) for t in b['tickets']}))
 def test_settlement_payout_unit_not_final_odds(self):
  r=settle(frozen(),finished(),payouts())
  self.assertEqual(r['status'],'settled')
  self.assertEqual(r['strategies']['axis6']['payout'],6150)
  self.assertEqual(r['strategies']['box10']['payout'],3690)
 def test_complete_losing_record(self):
  hs=finished()
  for i,h in enumerate(hs):h['着順']=str([4,5,1,2,6,3][i])
  ps=[{'３連複組番馬番1':'3','３連複組番馬番2':'4','３連複組番馬番3':'6','３連複払戻金（円）':'2000'}]
  r=settle(frozen(),hs,ps)
  self.assertFalse(r['strategies']['axis6']['hit']);self.assertEqual(r['strategies']['axis6']['payout'],0)
 def test_missing_payout_not_settled(self):
  self.assertEqual(settle(frozen(),finished(),[])['status'],'pending')
 def test_blank_finish_is_not_a_loss(self):
  hs=finished();hs[-1]['着順']=''
  self.assertEqual(settle(frozen(),hs,payouts())['status'],'review_required')
 def test_missing_runner_requires_refund_review(self):
  self.assertEqual(settle(frozen(),finished()[:-1],payouts())['status'],'review_required')
 def test_duplicate_payout_not_double_counted(self):
  self.assertEqual(settle(frozen(),finished(),payouts()*2)['strategies']['axis6']['payout'],6150)
 def test_conflicting_payout_requires_review(self):
  ps=payouts()*2;ps[1]=dict(ps[1],**{'３連複払戻金（円）':'9990'})
  self.assertEqual(settle(frozen(),finished(),ps)['status'],'review_required')
 def test_dead_heat_two_winning_tickets_paid(self):
  hs=finished();hs[3]['着順']='3'
  ps=payouts()+[dict(payouts()[0],**{'３連複組番馬番3':'4','３連複払戻金（円）':'850'})]
  r=settle(frozen(),hs,ps)
  self.assertEqual(r['status'],'settled');self.assertEqual(r['strategies']['axis6']['payout'],10400)
 def test_incomplete_dead_heat_is_not_settled(self):
  hs=finished();hs[3]['着順']='3'
  self.assertEqual(settle(frozen(),hs,payouts())['status'],'review_required')
 def test_hash_chain_detects_changes(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'ledger';l=Ledger(p);l.append('prediction','k',{'value':1},NOW)
   self.assertEqual(len(Ledger(p).events),1)
   p.write_text(p.read_text().replace('"value":1','"value":2'))
   with self.assertRaises(ValueError):Ledger(p)
 def test_appends_preserve_prior_observations(self):
  with tempfile.TemporaryDirectory() as d:
   l=Ledger(Path(d)/'ledger');first=l.append('result','k',{'status':'pending'},NOW)
   l.append('result','k',{'status':'settled'},NOW)
   self.assertEqual(l.events[0],first);self.assertEqual(l.latest('result')['k']['payload']['status'],'settled')
 def test_cutoff_never_backdates(self):
  self.assertIn('固定期限',skip_reason(horses(),RACE,NOW+timedelta(minutes=26),META))
 def test_missing_body_weight_waits(self):
  hs=horses();hs[0]['馬体重']=''
  self.assertIn('馬体重',skip_reason(hs,RACE,NOW,META))
 def test_finished_data_cannot_become_new_prediction(self):
  self.assertIn('着順',skip_reason(finished(),RACE,NOW,META))
 def test_input_digest_excludes_final_popularity(self):
  p=frozen();hs=horses();hs[0]['人気']='15'
  q=snapshot_prediction(BUNDLE,hs,RACE,META,NOW)
  self.assertEqual(p['input_sha256'],q['input_sha256']);self.assertEqual(p['strategies'],q['strategies'])
 def test_reprocessing_cannot_change_fixed_tickets(self):
  import io,csv,zipfile
  def archive(hs):
   stream=io.BytesIO()
   with zipfile.ZipFile(stream,'w') as z:
    for kind,rows in [('horselist',hs),('racelist',[RACE]),('payback',[])]:
     if kind=='horselist':rows=[dict(h,**{k:RACE[k] for k in ['競走年月日','競馬場','レース番号']}) for h in rows]
     fields=list(rows[0]) if rows else ['競走年月日','競馬場','レース番号']
     out=io.StringIO();w=csv.DictWriter(out,fieldnames=fields);w.writeheader();w.writerows(rows);z.writestr('20261101_'+kind+'.csv',out.getvalue())
   return stream.getvalue()
  with tempfile.TemporaryDirectory() as d:
   state=Path(d);raw=archive(horses());process(state,raw,META,BUNDLE,{'sha256':'b'*64},NOW)
   old=Ledger(state/'ledger.jsonl').latest('prediction')
   hs=horses();hs[0]['全成績']='0-0-0-100'
   process(state,archive(hs),META,BUNDLE,{'sha256':'b'*64},NOW)
   self.assertEqual(old,Ledger(state/'ledger.jsonl').latest('prediction'))
 def test_duplicate_race_key_rejected(self):
  import io,zipfile
  # Real fixture generated above is not needed: duplicate race key test covers parser boundaries.
  with self.assertRaises(ValueError):indexed({'racelist':[RACE,RACE],'horselist':[],'payback':[]})
 def test_no_past_as_today(self):
  with tempfile.TemporaryDirectory() as d:
   state=Path(d);l=Ledger(state/'ledger.jsonl');p=frozen();p['date']='2026-10-31';l.append('prediction','old',p,NOW)
   latest,history=public_data(state,NOW,{'status':'ok'})
   self.assertEqual(latest['races'],[]);self.assertEqual(len(history['races']),1)
if __name__=='__main__':unittest.main()
