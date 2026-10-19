"""Source-order correctness for measured response assessment, not model accuracy."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from tracker import feedback_assessment as fa, strategy_profiles, graph_store, monitoring, monitor_evidence
from tracker.adapters import normalize
from tracker.store import Store
from tracker.schema import event
from tracker.semantic_extraction import read
from test_feedback_assessment import fixture, transport


class FeedbackAssessmentOrderTests(unittest.TestCase):
    def measure(self,run,choice='first'):
        with tempfile.TemporaryDirectory() as root:
            return fa.execute(run,root,transport(choice))

    def test_unknown_window_endpoint_or_expression_cannot_supply_positive_or_negative(self):
        for index in range(4):
            for choice in ['first','none']:
                with self.subTest(index=index,choice=choice):
                    run=fixture();run['events'][index]['order_known']=False
                    out,calls=self.measure(run,choice)
                    self.assertEqual(calls,0)
                    self.assertEqual(out['counts']['decidable'],0)
                    self.assertEqual(out['counts']['unknown'],1)
                    self.assertIsNone(out['observations'][0]['value'])
                    self.assertFalse(out['observations'][0]['closed_window'])
                    self.assertIn(run['events'][index]['id'],out['observations'][0]['unordered_event_ids'])

    def test_empty_unknown_expression_still_prevents_measured_absence(self):
        run=fixture(text=' ');run['events'][2]['order_known']=False
        out,calls=self.measure(run,'none')
        self.assertEqual((out['counts']['not_observed'],out['counts']['unknown'],calls),(0,1,0))

    def test_native_parallel_message_group_is_not_treated_as_serial(self):
        run=fixture();a=run['events'][0];a['source_message_index']=21
        other=deepcopy(a);other.update(id='parallel',index=.5,call_id='other')
        run['events'].append(other)
        out,calls=self.measure(run)
        self.assertEqual((out['counts']['unknown'],calls),(1,0))
        self.assertIn('batch',out['observations'][0]['reason'])

    def test_later_ordered_window_survives_earlier_unknown_response(self):
        run=fixture();run['events'][1]['order_known']=False
        event(run['events'],kind='feedback',text='installed',pointer='/b-result',trajectory_id='main',actor='environment',source_call_id='b')
        event(run['events'],kind='reasoning',text='Installation succeeded.',pointer='/b-assessment',trajectory_id='main')
        event(run['events'],kind='action',text='check version',pointer='/c',trajectory_id='main',call_id='c')
        before=deepcopy(run);out,calls=self.measure(run)
        self.assertEqual(out['counts']['assessed'],1)
        self.assertEqual(out['counts']['unknown'],1)
        self.assertEqual(out['counts']['decidable'],1)
        self.assertEqual(calls,1);self.assertEqual(run,before)
        self.assertEqual(out['observations'][1]['assessment_event_id'],'e6')

    def test_ordered_no_prose_window_still_supplies_zero_without_model_call(self):
        out,calls=self.measure(fixture(text=''))
        self.assertEqual((out['counts']['not_observed'],out['counts']['unknown'],calls),(1,0,0))

    def test_legacy_v2_result_replays_without_reinterpreting_original_windows(self):
        run=fixture();run['events'][1]['order_known']=False
        def decide(req):return ({k:{'value':'assessed'} for k in req['questions']},'test')
        old=fa.build(run,decide,version='feedback-assessment/2')
        self.assertEqual(old['counts']['assessed'],1)
        self.assertNotIn('unordered_event_ids',old['observations'][0])
        current=fa.build(run,lambda req:self.fail('Unordered window should not request inference'))
        self.assertEqual(current['counts']['unknown'],1)

    def test_upgrade_reuses_paid_selections_and_retains_old_result(self):
        run=fixture();run['events'][1]['order_known']=False
        event(run['events'],kind='feedback',text='installed',pointer='/b-result',trajectory_id='main',actor='environment',source_call_id='b')
        event(run['events'],kind='reasoning',text='Installation succeeded.',pointer='/b-assessment',trajectory_id='main')
        event(run['events'],kind='action',text='check version',pointer='/c',trajectory_id='main',call_id='c')
        with tempfile.TemporaryDirectory() as root:
            old,calls=fa.execute(run,root,transport(),version=fa.PREVIOUS)
            self.assertEqual((old['counts']['assessed'],calls),(2,2))
            current,calls=fa.execute(run,root,lambda req:self.fail('Unchanged semantic decisions must be reused'))
            self.assertEqual((current['counts']['assessed'],current['counts']['unknown'],calls),(1,1,0))
            saved=list((Path(root)/'history').glob('*.json'))
            self.assertEqual(len(saved),1);self.assertEqual(read(saved[0])['result'],old)
            self.assertTrue(fa.audit(run,old,root)['exact_replay'])
            self.assertTrue(fa.audit(run,current,root)['exact_replay'])
            again,calls=fa.execute(run,root,lambda req:self.fail('No new calls'))
            self.assertEqual(again,current);self.assertEqual(calls,0)

    def test_long_trace_reaches_database_monitors_graphs_and_strategy_with_same_denominator(self):
        # Scripted semantic responses isolate window/aggregation correctness.
        # This does not estimate the classifier's real-world accuracy.
        steps=[dict(action=f'cat logs/step-{i}.txt',observation='Run output saved.',
                    thought='The previous output was saved.' if i%2 else 'Read the next log.') for i in range(128)]
        steps.append(dict(action='echo finished',thought='Read the final log.'))
        run=normalize(dict(history=[dict(role='user',content='Review the run logs.')],trajectory=steps),
                      'swe-agent',{'experiment':'feedback-order-control','training_step':1})[0]
        for i,e in enumerate(e for e in run['events'] if e['kind']=='feedback'):
            if i%8 in {0,1}:e['order_known']=False
        def scripted(req):
            i=int(req['state']['action']['text'].split('step-')[1].split('.')[0])
            return transport('first' if i%2==0 else 'none')(req)
        with tempfile.TemporaryDirectory() as root:
            store=Store(Path(root)/'db.sqlite');store.add([run]);folder=Path(root)/'observation'
            result,calls=fa.execute(run,folder,scripted)
            self.assertEqual((result['counts']['assessed'],result['counts']['not_observed'],
                              result['counts']['unknown'],result['counts']['decidable'],calls),(48,48,32,96,96))
            saved=fa.register(store,run,result,folder)
            graph=graph_store.read(store,saved['graph_id'])
            edges=[e for e in graph['edges'] if e['type']=='assesses_response_group']
            self.assertEqual(len(edges),48)
            uncertain={e['id'] for e in run['events'] if e.get('order_known') is False}
            self.assertFalse(any(e['target'].removeprefix('event:') in uncertain for e in edges))
            monitor=monitoring.create(store,dict(name='Feedback assessment',kind='metric',
                observer=saved['observer'],metric='feedback_assessment_fraction'))
            monitoring.sync(store)
            measured=monitoring.cases(store,monitor['id'])['rows'][0]['measurement']
            receipt=monitor_evidence.read(store,measured['id'])
            self.assertEqual(receipt['measurement']['value'],.5)
            explanation=receipt['explanation']['feedback_assessment']
            self.assertEqual(explanation,result)
            profile=strategy_profiles.derive(dict(run_id=run['id'],observer=saved['observer'],source_hash=result['source_hash'],
                                                 feedback_assessment=result))
            counts=strategy_profiles.counts(profile['families']['feedback'],'feedback')
            self.assertEqual((counts['numerator'],counts['denominator'],counts['unknown']),(48,96,32))
            _,calls=fa.execute(run,folder,lambda req:self.fail('Restart must reuse selections'))
            self.assertEqual(calls,0)


if __name__=='__main__':unittest.main()
