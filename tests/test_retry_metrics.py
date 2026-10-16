from copy import deepcopy
import unittest
from tracker import retry_metrics as rm
from tracker.schema import digest
from tests.test_operation_outcomes import sample
from tracker.monitoring import chart


def fixture():
    run, bundle, result = sample()
    for e in run['events']:
        if e['id'] in {'e1', 'e4'}:e.update(tool='book', arguments={'amount': 10 if e['id']=='e1' else 20})
    d=bundle['document'];d['source_hash']=result['source_hash']=digest(run)
    d['operation_outcomes']=result;d['work_history']['available']=True
    d['work_history']['recurrences'][0]['supporting_identity_relations']=[{'from':'b','to':'a','type':'same_action_target'}]
    return run,d


class RetryMetricsTests(unittest.TestCase):
    def test_changed_retry_uses_bound_outcomes_and_keeps_evidence(self):
        r,d=fixture();before=deepcopy(d);v=rm.inspect(r,d)
        self.assertEqual(v['metrics']['changed_retry_completion_fraction']['numerator'],1)
        self.assertEqual(v['metrics']['changed_retry_completion_fraction']['denominator'],1)
        self.assertEqual(v['episodes'][0]['payload_changed'],True)
        self.assertIn('e5',v['episodes'][0]['evidence_ids']);self.assertEqual(d,before)

    def test_unknown_result_is_excluded_not_counted_as_failure(self):
        r,d=fixture();d['operation_outcomes']['observations']=[o for o in d['operation_outcomes']['observations'] if o['action_event_id']!='e4']
        v=rm.inspect(r,d)['metrics'];self.assertEqual(v['changed_retry_completion_fraction']['denominator'],0)
        self.assertEqual(v['changed_retry_unknown_fraction']['numerator'],1)

    def test_partial_result_counts_as_not_completed(self):
        r,d=fixture()
        for o in d['operation_outcomes']['observations']:
            if o['action_event_id']=='e4':o['outcome']='partial'
        m=rm.inspect(r,d)['metrics']['changed_retry_completion_fraction']
        self.assertEqual((m['numerator'],m['denominator']),(0,1))

    def test_identical_payload_is_separate_from_changed_retry(self):
        r,d=fixture();r['events'][3]['arguments']={'amount':10};d['operation_outcomes']['source_hash']=digest(r)
        v=rm.inspect(r,d)['metrics'];self.assertEqual(v['changed_retry_completion_fraction']['denominator'],0)
        self.assertEqual(v['unchanged_retry_fraction']['numerator'],1)

    def test_ambiguous_identity_absent_identity_and_future_feedback_do_not_count(self):
        for mode in ('disputed','missing','future'):
            r,d=fixture()
            if mode=='disputed':d['work_history']['streams']=[{'groups':[{'id':'g','disputed_identity':True}]}]
            if mode=='missing':d['work_history']['recurrences'][0]['supporting_identity_relations']=[]
            if mode=='future':r['events'][3]['index']=0;d['operation_outcomes']['source_hash']=digest(r)
            v=rm.inspect(r,d);self.assertEqual(v['episodes'],[],mode)
            self.assertIn('e1',v['failed_calls_without_selected_retry'])

    def test_duplicate_identity_does_not_duplicate_denominator(self):
        r,d=fixture();d['work_history']['recurrences']*=2
        self.assertEqual(len(rm.inspect(r,d)['episodes']),1)

    def test_missing_payload_cannot_be_called_a_change(self):
        r,d=fixture();r['events'][3].pop('arguments');d['operation_outcomes']['source_hash']=digest(r)
        v=rm.inspect(r,d);self.assertEqual(v['unknown_payload_count'],1)
        self.assertEqual(v['metrics']['changed_retry_completion_fraction']['denominator'],0)

    def test_unavailable_argument_placeholders_are_not_identical_native_calls(self):
        r,d=fixture()
        for e in r['events']:
            if e['id'] in {'e1','e4'}:e.update(arguments={},arguments_available=False)
        d['operation_outcomes']['source_hash']=digest(r)
        observed=rm.inspect(r,d)
        self.assertIsNone(observed['episodes'][0]['payload_changed'])
        self.assertEqual(observed['episodes'][0]['retry_outcome'],'completed')
        legacy=deepcopy(observed);legacy['schema']='same-work-retry/1';legacy['episodes'][0]['payload_changed']=False
        updated=rm.refresh(r,legacy)
        self.assertIsNone(updated['episodes'][0]['payload_changed']);self.assertEqual(legacy['episodes'][0]['payload_changed'],False)
        self.assertEqual(updated['metrics']['unchanged_retry_fraction']['denominator'],0)

    def test_genuine_empty_native_arguments_remain_comparable(self):
        self.assertEqual(rm.payload({'tool':'status','arguments':{}}),('status',{}))

    def test_training_bin_pools_opportunities_without_averaging_ratios(self):
        monitor={'kind':'metric','metric':'changed_retry_completion_fraction'}
        runs=[{'id':str(i),'metadata':{'experiment':'x','training_step':2}} for i in range(2)]
        rows={'0':{'value':1,'numerator':1,'denominator':1,'status':'available'},'1':{'value':0,'numerator':0,'denominator':9,'status':'available'}}
        c=chart(monitor,runs,rows);self.assertEqual(c['series'][0]['bins'][0]['value'],.1)
        self.assertEqual(c['aggregation'],'opportunity_ratio')
