"""Replay public-source development evidence, including failed intermediate outputs."""
import json
from pathlib import Path
import unittest

from tracker import work_content_stages as stages, work_content_bindings as links
from tracker.schema import InputError
from test_scoped_granularity_replay import required_matches


class CrossDomainWorkContentsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=json.loads((Path(__file__).parent/'fixtures/cross_domain_work_contents.json').read_text(encoding='utf-8'))

    def test_exact_source_and_each_content_protocol_remain_replayable(self):
        cases={}
        for row in self.data['contents']:
            with self.subTest(arm=row['arm'],case=row['case']):
                packet=row['packet'];uid=packet['units'][0]['unit_id']
                self.assertEqual(row['request'],stages.scoped_content_request(packet,uid,content_policy=row['policy']))
                bound=stages.bind_scoped_contents(packet,row['request'],row['response'],row['bound']['producer'],content_policy=row['policy'])
                self.assertEqual(bound,row['bound'])
                if 'original_response' in row:
                    with self.assertRaises(InputError):
                        stages.bind_scoped_contents(packet,row['request'],row['original_response'],row['bound']['producer'],content_policy=row['policy'])
                    self.assertEqual([(c['id'],c['kind'],c['mode']) for c in row['original_response']['contents']],
                                     [(c['id'],c['kind'],c['mode']) for c in row['response']['contents']])
                    self.assertEqual(row['repair_request']['repair']['attempt'],1)
                matched=required_matches(bound['contents'],row['reference']['required'])
                passed=matched==len(row['reference']['required']) and len(bound['contents'])==row['reference']['expected_count']
                self.assertEqual(row['check']['matched'],matched)
                self.assertEqual(row['check']['passes'],passed)
                cases.setdefault(row['arm'],[]).append(row['case'] if not passed else None)
        self.assertEqual([c for c in cases['baseline'] if c],['airline-eligibility','software-edit-and-check'])
        self.assertEqual([c for c in cases['structural'] if c],['airline-missing-id','control-future'])
        self.assertEqual([c for c in cases['complete'] if c],[])
        self.assertEqual({k:len(v) for k,v in cases.items()},dict(baseline=7,structural=11,complete=11))

    def test_relationship_receipts_preserve_all_decisions_and_ambiguities(self):
        totals={}
        for arm,rows in self.data['relations'].items():
            fp=fn=0
            for row in rows:
                if row.get('status')=='inventory_incomplete':
                    self.assertNotIn('requests',row)
                    continue
                policy=row['review']['schema']
                requests=links.local_relation_requests(row['packet'],row['bound'],policy=policy)
                self.assertEqual(requests,row['requests'])
                responses={r['page']:r['response'] for r in row['review']['receipts']}
                review=links.local_relation_review(row['packet'],row['bound'],responses,policy=policy)
                self.assertEqual(review,row['review'])
                selected={(r['source'],r['target'],r['type']) for r in review['links'] if r['status']=='supported'}
                positive={tuple(r) for r in row['reference']['positive']}
                ambiguous={tuple(r) for r in row['reference']['ambiguous']}
                self.assertEqual(sorted(selected-positive-ambiguous),[tuple(r) for r in row['score']['false_positive']])
                self.assertEqual(sorted(positive-selected),[tuple(r) for r in row['score']['false_negative']])
                self.assertEqual(sorted(selected & ambiguous),[tuple(r) for r in row['score']['ambiguous_selected']])
                fp+=len(selected-positive-ambiguous);fn+=len(positive-selected)
            totals[arm]=dict(false_positive=fp,false_negative=fn)
        self.assertEqual(totals['baseline'],dict(false_positive=6,false_negative=0))
        self.assertEqual(totals['refined'],dict(false_positive=0,false_negative=0))
        self.assertEqual(totals['final'],dict(false_positive=1,false_negative=0))
        # These are different subsets, not a before/after population accuracy.
        self.assertEqual(len(self.data['relations']['refined']),3)
        self.assertEqual(len(self.data['relations']['final']),2)
        self.assertEqual(self.data['usage']['jev_calls'],12)
        self.assertIsNone(self.data['usage']['candidate_token_usage'])


if __name__=='__main__':unittest.main()
