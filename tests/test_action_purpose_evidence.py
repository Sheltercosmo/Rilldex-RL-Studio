"""Exact live receipt replay and combined-dispatch propagation, not accuracy estimation."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.evaluate_reading_context import score, conversation
from tracker import action_reading, behavior_distributions
from tracker.adapters import normalize
from tracker.jev import JevClient, QUESTIONS
from tracker.observe import analyze
from tracker.schema import digest
from tracker.store import Store
from receipt_replay import recorded_sqlite_metadata


class ActionPurposeEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=json.loads(Path('tests/fixtures/action_purpose_evidence.json').read_text(encoding='utf8'))
        cls.enterClassContext(recorded_sqlite_metadata(cls.data))
        cls.sources={r['id']:r for r in cls.data['sources']}

    def test_failed_trials_and_original_ambiguous_references_remain_reproducible(self):
        for key,receipt in self.data['receipts'].items():
            self.assertEqual(digest(receipt['request']),key)
            self.assertEqual(receipt['response']['model'],receipt['request']['model'])
        for phase in self.data['phases'].values():
            for row in phase['results']:
                receipt=self.data['receipts'][row['request_hash']]
                self.assertEqual(score(receipt['response'],{**row,'request':receipt['request']}),row['scores'])
        broad=self.data['phases']['broad']['groups']
        self.assertEqual(broad['authored/candidate']['failures'],['clarification'])
        holdout=self.data['phases']['holdout']['groups']
        self.assertEqual(holdout['authored_holdout/candidate']['failures'],['heldout-2'])
        ambiguous=[r for r in self.data['phases']['minimal']['results'] if r['kind']=='ambiguous_original']
        self.assertEqual(len(ambiguous),2)
        self.assertTrue(all(r['reference']['mode']=='apply' and not r['scores']['mode']['correct'] for r in ambiguous))

    def test_current_full_requests_match_all_28_live_controls(self):
        self.assertEqual(len(self.data['current']),28)
        for row in self.data['current']:
            with self.subTest(case=row['id']):
                run=normalize(self.sources[row['id']]['document'])[0]
                request=JevClient().request(run,row['action_id'])
                receipt=self.data['receipts'][row['request_hash']]
                self.assertEqual(request,receipt['request'])
                self.assertEqual(digest(run),row['source_hash'])
                self.assertTrue(score(receipt['response'],{**row,'request':request})['mode']['correct'])

    def test_three_live_combinations_reach_flow_distribution_and_cached_evidence(self):
        selected=[r for r in self.data['current'] if r['reference']['mode']=='mixed']
        self.assertEqual(len(selected),3)
        for row in selected:
            with self.subTest(case=row['id']), tempfile.TemporaryDirectory() as directory, patch('urllib.request.urlopen',side_effect=AssertionError('Offline receipt replay')):
                receipt=self.data['receipts'][row['request_hash']]
                run=normalize(self.sources[row['id']]['document'])[0]
                def replay(request):
                    self.assertEqual(request,receipt['request'])
                    return deepcopy(receipt['response'])
                client=JevClient(transport=replay)
                store=Store(Path(directory)/'flow.sqlite');store.add([run])
                reading=action_reading.read(store,run['id'],row['action_id'],client=client)
                self.assertEqual(reading['fields']['mode']['value'],'mixed')
                self.assertEqual(reading['fields']['mode']['status'],'decided')
                flow=action_reading.flow(store,run['id'],client=client)
                self.assertEqual(flow['purposes'],{'mixed':1})
                self.assertEqual(flow['coverage']['purpose_decided'],1)
                d=behavior_distributions.snapshot(store,lens='action_purpose')
                self.assertEqual(d['distribution']['counts']['mixed'],1)
                self.assertEqual(d['distribution']['counts']['unknown'],0)
                self.assertEqual(d['reading_coverage']['decided'],1)
                self.assertEqual(d['cases'][0]['reading']['value'],'mixed')
                frozen=behavior_distributions.save_comparison(store,{'controls':{'lens':'action_purpose'}})
                self.assertEqual(frozen['snapshot']['cases'][0]['reading']['value'],'mixed')
                self.assertEqual(behavior_distributions.read_comparison(store,frozen['id']),frozen)
                self.assertEqual(store.get(run['id'])['analysis']['metrics']['mode_counts']['mixed'],1)
                cached=action_reading.read(store,run['id'],row['action_id'],client=JevClient(transport=lambda r:self.fail('Saved current request must be reused')))
                self.assertEqual(cached['fields']['mode']['value'],'mixed')

    def test_known_combination_does_not_invent_an_internal_check_or_closure(self):
        doc=conversation('Fix the configuration and check it.',
            [('operation',{'value':4},None,'Write the setting and run acceptance assertions.')],
            {'operation':'Write the setting and run tests.'})
        run=normalize(doc)[0];eid=next(e['id'] for e in run['events'] if e['kind']=='action')
        result=analyze(run,{eid:{'mode':{'status':'decided','value':'mixed','source':'review'}}})
        evidence=result['verification']
        self.assertEqual(evidence['checks'],[])
        self.assertEqual(evidence['actor_tails'][0]['status'],'unresolved')
        self.assertEqual(evidence['actor_tails'][0]['combined_purpose_event_ids'],[eid])
        self.assertEqual(result['metrics']['mode_counts']['mixed'],1)
        self.assertIn('mixed',QUESTIONS['mode']['criteria'])


if __name__=='__main__':unittest.main()
