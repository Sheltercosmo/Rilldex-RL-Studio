"""Frozen live temporal readings, protocol compatibility and paging contracts."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from tracker import local_order, work_content_bindings as links
from tracker.jev import validate_answers
from tracker.schema import InputError, dumps


class LocalOrderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=json.loads((Path(__file__).parent/'fixtures/local_order.json').read_text(encoding='utf-8'))

    def test_live_frozen_temporal_readings_and_exact_requests(self):
        for row in self.data['final']:
            with self.subTest(case=row['case']):
                requests=links.local_relation_requests(row['packet'],row['bound'])
                self.assertEqual(requests['order-0'],row['request'])
                review=links.local_relation_review(row['packet'],row['bound'],{'order-0':row['response']})
                order=[r for r in review['links'] if r['type']=='before']
                self.assertEqual(order,row['temporal_links'])
                self.assertEqual(sorted([r['source'],r['target']] for r in order if r['status']=='supported'),sorted(row['expected']))
                self.assertTrue(all(r['status']=='pending' for r in review['links'] if r['type']!='before'))
                self.assertEqual(len({r['id'] for r in review['links']}),len(review['links']))
                legacy=links.local_relation_review(row['packet'],row['bound'],{},policy=links.CONTRAST_LOCAL_RELATIONS)
                self.assertEqual([(r['id'],r['source'],r['target'],r['type']) for r in review['links']],
                                 [(r['id'],r['source'],r['target'],r['type']) for r in legacy['links']])
        self.assertEqual(len(self.data['final']),17)

    def test_argmax_direction_and_unresolved_never_override_or_duplicate(self):
        row=next(r for r in self.data['final'] if r['case']=='before-clause')
        req=row['request']
        for choice in req['questions']['c1_c2']['criteria']:
            response=dict(model=req['model'],answers={'c1_c2':dict(type='choice',confidence=0,
                choice='later' if choice=='earlier' else 'earlier',
                probabilities={v:float(v==choice) for v in req['questions']['c1_c2']['criteria']})})
            answers=validate_answers(response,req)
            self.assertEqual(answers['c1_c2']['value'],choice)
            result=links.local_relation_review(row['packet'],row['bound'],{'order-0':response})
            temporal=[r for r in result['links'] if r['type']=='before']
            self.assertLessEqual(sum(r['status']=='supported' for r in temporal),1)
            self.assertEqual(tuple(r['status'] for r in temporal),local_order.statuses(choice))
            self.assertTrue(all(r['reading']==choice for r in temporal))

    def test_keys_cannot_collide_with_underscores_and_every_pair_is_preserved(self):
        contents=[dict(id=id,expression=dict(text=id)) for id in ('a_b','c','a','b_c','a_b_c')]
        pairs=local_order.pairs(contents)
        self.assertEqual(len(pairs),10)
        self.assertEqual(len({tuple(c['id'] for c in p) for p in pairs.values()}),10)

    def test_paging_retains_complete_source_and_never_truncates(self):
        row=self.data['final'][0];source=row['packet']['units'][0]['source']
        contents=[dict(id='c'+str(i),expression=dict(text='content '+str(i))) for i in range(9)]
        pages=local_order.requests(source,contents,page_size=32,max_bytes=9000)
        self.assertGreater(len(pages),2)
        self.assertEqual(sum(len(r['questions']) for r in pages.values()),36)
        for req in pages.values():
            self.assertEqual(req['state']['source'],source['text'])
            self.assertLessEqual(len(dumps(req).encode()),9000)
        with self.assertRaises(InputError):
            local_order.requests(source,contents,page_size=32,max_bytes=100)
        self.assertEqual(local_order.requests(source,[],page_size=32,max_bytes=100),{})

    def test_discarded_readings_remain_visible(self):
        joint=self.data['joint']
        self.assertEqual(sum(r['selected']!=sorted(r['expected']) for r in joint),5)
        self.assertTrue(any(r['selected']!=r['expected'] for r in self.data['discarded']['anchored']))
        self.assertTrue(any(r['selected']!=r['expected'] for r in self.data['discarded']['exact']))


if __name__=='__main__':unittest.main()
