"""Distribution arithmetic and frozen-reading controls, not semantic accuracy."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tracker import behavior_distributions as distributions, action_distributions
from tracker.adapters import normalize
from tracker.jev import JevClient
from tracker.schema import dumps, digest
from tracker.store import Store
from test_tracker import harbor, response_for


class ActionDistributionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        self.store = Store(Path(directory.name)/'distribution.sqlite')

    def run_source(self, step=1, task='fixed task'):
        raw = harbor(); raw['steps'][-1]['message'] += str(step)+task
        run = normalize(raw, 'harbor', {'experiment':'trial','task_id':task,'training_step':step})[0]
        self.store.add([run]); return run

    def record(self, run, number=0, mode='explore', model=None, stale=False):
        event = [e for e in run['events'] if e['kind']=='action'][number]
        client = JevClient(transport=lambda request:{**response_for(request), 'model':request['model']}, **({'model':model} if model else {}))
        result = client.evaluate(run, event['id'])
        result['mode'] = {'status':'decided','value':mode,'source':'jev', 'probabilities':{mode:1}}
        if stale: result['_provenance']['harness'] = 'old-reader'
        p = result['_provenance']
        self.store.record(run['id'],event['id'],p['harness'],p['model'],p['packet_hash'],result)
        return event, result

    def snapshot(self, **kwargs):
        with patch('tracker.jev.JevClient._post', side_effect=AssertionError('No inference')):
            return distributions.snapshot(self.store, lens='action_purpose', **kwargs)

    def test_every_action_stays_in_partial_denominator_without_heuristic_labels(self):
        run = self.run_source(); event,_ = self.record(run)
        result = self.snapshot()
        self.assertEqual(result['distribution']['total'],3)
        self.assertEqual(result['distribution']['counts']['explore'],1)
        self.assertEqual(result['distribution']['counts']['unknown'],2)
        self.assertEqual(result['distribution']['shares']['explore'],1/3)
        self.assertEqual(result['reading_coverage']['inspected'],1)
        self.assertEqual({r['event_id'] for r in result['cases']},{e['id'] for e in run['events'] if e['kind']=='action'})
        case = next(r for r in result['cases'] if r['event_id']==event['id'])
        self.assertIn('action_reading=1',case['map_url'])
        self.assertEqual(case['reading']['value'],'explore')
        self.assertEqual(result['inference_calls'],0)

    def test_reader_models_never_pool(self):
        run = self.run_source()
        self.record(run,mode='explore',model='reader-a')
        self.record(run,mode='verify',model='reader-b')
        first = self.snapshot(); self.assertEqual(len(first['observers']),2)
        docs = action_distributions.inputs(self.store,'action_purpose')
        for doc in docs:
            value = self.snapshot(observer=doc['observer'])
            expected = 'explore' if doc['reader_profile']['model']=='reader-a' else 'verify'
            self.assertEqual(value['distribution']['counts'][expected],1)
            self.assertEqual(value['distribution']['total'],3)
            self.assertEqual(value['reader_profile'],doc['reader_profile'])

    def test_unobserved_rollouts_and_old_readings_do_not_turn_into_zero_behavior(self):
        observed = self.run_source(1); self.record(observed)
        old = self.run_source(2); self.record(old, stale=True)
        self.run_source(3)
        value = self.snapshot()
        self.assertEqual(value['population'],3)
        self.assertEqual(value['observed_rollouts'],1)
        self.assertEqual(value['observation_readiness']['statuses']['not_observed'],2)
        self.assertIsNone(value['current']['shares']['explore'])
        self.assertFalse(value['comparable'])
        self.record(observed,1,stale=True)
        value = self.snapshot()
        self.assertEqual(value['reading_coverage']['outdated'],1)
        self.assertEqual(value['distribution']['counts']['unknown'],2)

    def test_reviewed_reading_and_saved_comparison_survive_later_model_updates(self):
        run = self.run_source(); event,_ = self.record(run)
        second = self.run_source(2); self.record(second,mode='verify')
        before = distributions.save_comparison(self.store,{'controls':{'lens':'action_purpose','experiment':'trial'}})
        with self.store.connect() as c:
            review = dict(event_id=event['id'],field='mode',value='apply',reviewer='Control reviewer',
                note='Authored arithmetic control',evidence_ids=[event['id']])
            c.execute('INSERT INTO reviews(run_id,payload,created_at) VALUES (?,?,?)',(run['id'],dumps(review),'2026-11-07T00:00:00Z'))
        self.record(run,mode='verify')
        after = distributions.save_comparison(self.store,{'parent_id':before['id']})
        self.assertEqual(before,distributions.read_comparison(self.store,before['id']))
        self.assertEqual(before['snapshot']['baseline']['counts']['explore'],1)
        self.assertEqual(after['snapshot']['baseline']['counts']['apply'],1)
        case = next(c for c in after['snapshot']['cases'] if c['run_id']==run['id'] and c['id']==event['id'])
        self.assertEqual(case['reading']['reviewer'],'Control reviewer')
        self.assertNotEqual(before['snapshot']['snapshot_id'],after['snapshot']['snapshot_id'])

    def test_task_scope_and_missing_progress_are_preserved(self):
        self.record(self.run_source(1))
        self.record(self.run_source(2,task='another task'))
        run = self.run_source(3); run['id']='unplaced-control';run['metadata'].pop('training_step');self.store.add([run]);self.record(run)
        value = self.snapshot()
        self.assertEqual(len(value['cohorts']),3)
        self.assertEqual(value['observed_rollouts'],1)
        self.assertEqual(value['unplaced_rollouts'],0)
        self.assertEqual([b['step'] for b in value['bins']],[1,3])
        unplaced = next(c for c in value['cohorts'] if c['metadata'].get('comparison_basis') is None and c['metadata'].get('task_id')=='fixed task')
        separate = self.snapshot(cohort_id=unplaced['id'])
        self.assertEqual(separate['unplaced_rollouts'],1)
        self.assertEqual(separate['bins'],[])

    def test_goal_relationship_uses_its_own_field_not_action_purpose(self):
        run = self.run_source(); event,_ = self.record(run)
        with self.store.connect() as c:
            review = dict(event_id=event['id'],field='goal_relation',value='outside',reviewer='Control reviewer',
                note='Authored relationship control',evidence_ids=[event['id']])
            c.execute('INSERT INTO reviews(run_id,payload,created_at) VALUES (?,?,?)',(run['id'],dumps(review),'2026-11-07T00:00:00Z'))
        result = distributions.snapshot(self.store,lens='task_connection')
        self.assertEqual(result['distribution']['counts']['outside'],1)
        self.assertEqual(result['distribution']['counts']['unknown'],2)
        self.assertEqual(self.snapshot()['distribution']['counts']['explore'],1)

    def test_field_review_works_without_a_model_and_does_not_observe_other_fields(self):
        run = self.run_source(); event = next(e for e in run['events'] if e['kind']=='action')
        with self.store.connect() as c:
            review = dict(event_id=event['id'],field='mode',value='verify',reviewer='Control reviewer',
                note='Authored review-only control',evidence_ids=[event['id']])
            c.execute('INSERT INTO reviews(run_id,payload,created_at) VALUES (?,?,?)',(run['id'],dumps(review),'2026-11-07T00:00:00Z'))
        value = self.snapshot()
        self.assertEqual(value['reading_coverage']['reviewed'],1)
        self.assertEqual(value['reading_coverage']['current'],0)
        self.assertEqual(value['distribution']['counts']['verify'],1)
        self.assertEqual(distributions.snapshot(self.store,lens='task_connection')['observed_rollouts'],0)

    def test_source_copy_and_rollout_link_preserve_population_identity(self):
        from tracker.action_reading import flow
        from urllib.parse import parse_qs, urlsplit
        raw = harbor();raw['steps'][2]['is_copied_context']=True
        run = normalize(raw,'harbor',{'experiment':'scope / one','task_id':'same task','training_step':1})[0]
        self.store.add([run]);self.record(run)
        result = self.snapshot()
        self.assertEqual(result['distribution']['total'],2)
        self.assertEqual({c['id'] for c in result['cases']},{e['id'] for e in run['events'] if e['kind']=='action' and not e.get('copied_context')})
        link = parse_qs(urlsplit(flow(self.store,run['id'])['comparison_url']).query)
        self.assertEqual(link['experiment'],['scope / one'])
        self.assertEqual(link['cohort_id'],[result['cohort_id']])
        self.assertEqual(link['lens'],['action_purpose'])

    def test_pinned_public_trace_retains_exact_two_readings_and_all_unread_actions(self):
        from receipt_replay import recorded_sqlite_metadata
        from scripts.evaluate_feedback_reading import cases
        case = next(c for c in cases() if c['id']=='public-universe-e31')
        run = normalize(case['document'])[0]; self.store.add([run])
        evidence = json.loads(Path('tests/fixtures/feedback_reading_evidence.json').read_text(encoding='utf8'))
        self.enterContext(recorded_sqlite_metadata(evidence))
        def replay(request):
            receipt = evidence['receipts'][digest(request)]
            self.assertEqual(receipt['request'],request); return receipt['response']
        client = JevClient(transport=replay)
        for eid in ('e31','e163'):
            result = client.evaluate(run,eid); p=result['_provenance']
            self.store.record(run['id'],eid,p['harness'],p['model'],p['packet_hash'],result)
        value = self.snapshot()
        self.assertEqual(value['distribution']['total'],55)
        self.assertEqual(value['reading_coverage']['current'],2)
        self.assertEqual(value['reading_coverage']['uninspected'],53)
        self.assertEqual(value['unplaced_rollouts'],1)
        self.assertEqual(value['bins'],[])
