import copy
import tempfile
import unittest
from pathlib import Path

from tracker import policy_age as p, training_lineage, training_health
from tracker.schema import InputError
from tracker.store import Store


def clock(index=0, name='job/actor', unit='optimizer_update'):
    return {'schema':p.CLOCK_VERSION,'clock':name,'unit':unit,'index':index}


def history(n=4, index=0): return p.uniform_history(clock(index),n)


class PolicyAgeTests(unittest.TestCase):
    def test_optimizer_clock_skips_deduplicates_and_invalidates(self):
        c=p.OptimizerClock('test')
        c.advance(0,skipped=True,synchronized=True)
        self.assertEqual(c.snapshot()['index'],0)
        c.advance(1,skipped=False,synchronized=True)
        c.advance(1,skipped=False,synchronized=True)
        self.assertEqual(c.snapshot()['index'],1)
        with self.assertRaises(InputError):c.advance(1,skipped=True,synchronized=True)
        self.assertIsNone(c.snapshot())
        c.advance(2,skipped=False,synchronized=True)
        self.assertIsNone(c.snapshot())

    def test_uniform_mixed_partial_and_foreign_clock(self):
        h=history();self.assertEqual(p.observe(h,clock(2),4)['uniform_age'],2)
        h['segments']=[{'start':0,'end':2,'policy':clock(0)}, {'start':2,'end':4,'policy':clock(1)}]
        o=p.observe(h,clock(2),4)
        self.assertTrue(o['complete']);self.assertIsNone(o['uniform_age'])
        self.assertEqual(o['ages'],[{'age':1,'tokens':2},{'age':2,'tokens':2}])
        self.assertEqual(o['generation_history'],h)
        h['segments'][1]['start']=3
        o=p.observe(h,clock(2),4)
        self.assertFalse(o['complete']);self.assertEqual(o['known_tokens'],3)
        self.assertEqual(o['excluded_tokens'],{'generation_policy_unrecorded':1})
        for ref in [clock(2,name='another/actor'),clock(2,unit='policy_publication')]:
            o=p.observe(history(),ref,4)
            self.assertEqual(o['known_tokens'],0);self.assertEqual(o['excluded_tokens']['different_clock'],4)

    def test_no_substitution_or_negative_clamping(self):
        self.assertEqual(p.observe(None,clock(),4)['state'],'missing_generation_history')
        self.assertEqual(p.observe(history(),None,4)['state'],'missing_learner_clock')
        self.assertEqual(p.observe(history(),clock(),5)['state'],'token_count_mismatch')
        self.assertEqual(p.observe(history(index=4),clock(2),4)['excluded_tokens'],{'generation_after_learner':4})
        self.assertIsNone(p.observe(history(n=0),clock(),0)['uniform_age'])

    def test_bad_shapes_rejected(self):
        for change in [dict(index=True),dict(index=-1),dict(unit='checkpoint'),dict(index=2**53),dict(clock='')]:
            with self.assertRaises(InputError):p.validate_clock({**clock(),**change})
        h=history();h['segments'].append({'start':1,'end':2,'policy':clock()})
        with self.assertRaises(InputError):p.validate_history(h)
        h=history();h['segments'][0]['end']=5
        with self.assertRaises(InputError):p.validate_history(h)

    def test_clock_units_are_not_pooled_and_reuse_counts_again(self):
        observations=[p.observe(history(),clock(2),4),p.observe(history(),clock(2),4),
                      p.observe(p.uniform_history(clock(unit='policy_publication'),2),clock(3,unit='policy_publication'),2)]
        s=p.summarize([{'policy_age':o} for o in observations])
        self.assertEqual(len(s['clocks']),2)
        first=next(c for c in s['clocks'] if c['unit']=='optimizer_update')
        self.assertEqual(first['known_tokens'],8);self.assertEqual(first['mean_age'],2)

    def test_v1_v2_records_replay_with_explicit_history_only(self):
        for version in ('training-records/1','training-records/2'):
            with self.subTest(version=version),tempfile.TemporaryDirectory() as tmp:
                store=Store(Path(tmp)/'data.sqlite')
                ref={'producer':'p',('id' if version.endswith('/2') else 'rollout_id'):'s'}
                packet={'schema':version,'producer':'p','experiment':'e','records':[
                    {'id':'s','revision':0,'kind':'sample','sample':ref,'evidence':{'basis':'authored control'},
                     'data':{'split':'train','step':999,'step_basis':'generation','policy_history':history()}},
                    {'id':'u','revision':0,'kind':'use','sample':ref,'evidence':{'basis':'authored control'},
                     'data':{'batch_id':'b','learner_step':3,'stage':'backward_completed','model_tokens':4,'learner_policy':clock(2)}}]}
                training_lineage.receive(store,packet);training_lineage.receive(store,packet)
                stream=training_health.snapshot(store)['cohorts'][0]['uses'][0]
                self.assertEqual(stream['policy_age']['clocks'][0]['mean_age'],2)
                self.assertEqual(stream['policy_age']['receipts'],1)
                self.assertEqual(stream['points'][0]['step'],3)
                original=copy.deepcopy(packet)
                packet['records'][0]['revision']=1
                with self.assertRaises(InputError):training_lineage.receive(store,packet)
                # An older independent import has no history; opaque names and
                # seemingly compatible step numbers must not fill it in.
                original['records'][0]['data'].pop('policy_history')
                original['records'][0]['data']['policy_version']='checkpoint-1'
                store=Store(Path(tmp)/'legacy.sqlite');training_lineage.receive(store,original)
                stream=training_health.snapshot(store)['cohorts'][0]['uses'][0]
                self.assertEqual(stream['policy_age']['observed_uses'],0)
                self.assertEqual(stream['policy_age']['states'],{'missing_generation_history':1})

    def test_behavior_deduplicates_source_per_age_not_per_use(self):
        samples=[{'id':'a','run_id':'shared','monitor_population':'included','measurement':{'status':'available','value':.5}},
                 {'id':'b','run_id':'shared','monitor_population':'included','measurement':{'status':'available','value':.5}},
                 {'id':'c','run_id':'other','monitor_population':'included','measurement':{'status':'available','value':1}}]
        rows=[]
        for sid,age in [('a',0),('a',0),('b',0),('c',0),('a',1)]:
            rows.append({'sample':{'id':sid},'policy_age':p.observe(history(),clock(age),4)})
        result=p.behavior_groups(rows,samples,lambda s:{'id':s['id']})
        self.assertEqual(result['groups'][0]['mean_per_rollout'],.75)
        self.assertEqual(result['groups'][0]['receipts'],4)
        self.assertEqual(result['sources_in_multiple_groups'],1)


if __name__=='__main__':unittest.main()
