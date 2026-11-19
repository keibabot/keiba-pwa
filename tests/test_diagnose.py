import unittest
from research.diagnose import classify,counterfactual
class DiagnosisTest(unittest.TestCase):
 def test_partition(self):
  self.assertEqual(classify({1,2,3},[(1,3,2)],[(1,2,3)],100,0),'B')
  self.assertEqual(classify({1,2,4},[],[(1,2,3)],100,0),'A')
  self.assertEqual(classify({1,2,3},[(1,2,3)],[(1,2,3)],300,300),'C')
  self.assertEqual(classify({1,2,3},[(1,2,3)],[(1,2,3)],300,400),'profitable_hit')
  self.assertEqual(classify(set(),[],[],100,0,settled=False),'D')
  self.assertEqual(classify({1,2,3},[],[],100,0,refund=100),'D')
 def test_outside_does_not_use_finish(self):
  p={'horses':[dict(number=n,observed_popularity=n,reasons=['全成績: 10走中4回3着以内']) for n in range(1,10)]}
  plans,out=counterfactual(p)
  self.assertEqual(out,[6,7,8,9])
  for ts in plans.values():
   self.assertLessEqual(len(ts),12);self.assertEqual(len(ts),len(set(ts)))
   self.assertTrue(all(len(set(t))==3 for t in ts))
  self.assertTrue(all(set(t).isdisjoint(range(1,6)) for t in plans['outside_only12']))
