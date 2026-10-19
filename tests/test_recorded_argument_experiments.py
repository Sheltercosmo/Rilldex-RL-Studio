"""Recorded failed variants must not be described as improved default accuracy."""
from collections import defaultdict
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from tracker import work_argument_pairs as pairs
from tracker.jev import validate_answers
from tracker.schema import digest

FIXTURE=Path(__file__).parent/'fixtures/feature-membership/argument-occurrence-experiments.json'

class RecordedArgumentExperimentTests(unittest.TestCase):
    def test_all_recorded_choices_replay_without_calls_or_reference_changes(self):
        data=json.loads(FIXTURE.read_text(encoding='utf-8'))
        totals=defaultdict(lambda:dict(matching_roles=0,roles=0,complete=0,cases=0))
        with patch('tracker.jev.JevClient._post',side_effect=AssertionError('offline only')):
            for row in data['rows']:
                wire=data['wire'][row['request_hash']];original=deepcopy(wire['request'])
                self.assertEqual(digest(original),row['request_hash'])
                req=deepcopy(original)
                for key,order in row['criterion_order'].items():
                    criteria=req['questions'][key]['criteria']
                    self.assertEqual(set(order),set(criteria));self.assertEqual(len(order),len(criteria))
                    req['questions'][key]['criteria']={k:criteria[k] for k in order}
                if row['study']=='holders':
                    req['state'].update(missingness={'truncated_event_ids':[]},cutoff_event_id=req['state']['source']['event_id'])
                actual={k:v['value'] for k,v in validate_answers(wire['response'],req).items()}
                reference=row['reference'];t=totals[(row['study'],row['arm'])]
                keys=[k for k in reference if k.startswith('role__') or row['study']=='holders']
                t['matching_roles']+=sum(actual[k]==reference[k] for k in keys);t['roles']+=len(keys)
                t['complete']+=actual==reference;t['cases']+=1
                self.assertEqual(wire['request'],original)
        self.assertEqual(totals[('frames','baseline')],dict(matching_roles=19,roles=21,complete=5,cases=8))
        self.assertEqual(totals[('frames','frames')],dict(matching_roles=19,roles=21,complete=6,cases=8))
        self.assertEqual(totals[('holders','holder')],dict(matching_roles=4,roles=5,complete=1,cases=2))
        self.assertEqual(totals[('compact','baseline')],dict(matching_roles=37,roles=39,complete=15,cases=19))
        self.assertEqual(totals[('compact','compact')],dict(matching_roles=33,roles=39,complete=12,cases=19))
        self.assertEqual(len(data['wire']),48)

    def test_failed_variants_are_not_supported_selectors(self):
        self.assertEqual(pairs.VERSIONS,('work-argument-pairs/1','work-argument-pairs/2'))

if __name__=='__main__':unittest.main()
