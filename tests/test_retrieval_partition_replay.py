"""Exact quote conversion may strip duplicate prose, never repair evidence."""
from copy import deepcopy
import unittest

from research import retrieval_rollout_trial as trial
from research.retrieval_partition_replay import normalize
from tracker.schema import InputError
from tracker.semantic_extraction import read


class RetrievalPartitionReplayTests(unittest.TestCase):
    def setUp(self):
        root=trial.DEST/'jobs/55965fa4dab4d57cd190ad8a6650b726f2b946e5036acb846f233f223b865f28'
        self.req=read(root/'packet.json')['request'];self.body=read(root/'output.json')
        _,self.run=trial.workspace.load(trial.OBSERVER)

    def test_exact_source_and_descriptions_survive(self):
        before=deepcopy(self.body)
        result=normalize(self.run,self.req,self.body)
        self.assertEqual(self.body,before)
        self.assertEqual(result['partitions'][0]['spans'],[{'start':0,'end':753}])
        for key in ('contributions','rationale'):
            self.assertEqual(result['partitions'][0][key],before['partitions'][0][key])

    def test_conflicting_duplicate_is_not_silently_dropped(self):
        self.body['partitions'][0]['units'][0]['contribution']='Different meaning'
        with self.assertRaisesRegex(InputError,'descriptions differ'):
            normalize(self.run,self.req,self.body)

    def test_wrong_or_incomplete_quote_still_rejected(self):
        unit=self.body['partitions'][0]['units'][0]
        unit['quote']=unit['quote'].replace('1862','1863',1)
        with self.assertRaises(InputError):normalize(self.run,self.req,self.body)
        unit['quote']=self.req['source']['text'][:-30]
        with self.assertRaises(InputError):normalize(self.run,self.req,self.body)

    def test_unknown_property_is_not_discarded(self):
        self.body['partitions'][0]['units'][0]['claim']='Invented claim'
        with self.assertRaisesRegex(InputError,'Unsupported'):
            normalize(self.run,self.req,self.body)
