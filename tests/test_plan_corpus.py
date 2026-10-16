"""Synthetic fixtures verify sampling and temporal isolation, not tag accuracy."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_reasoningflow_audit import document
from research.plan_corpus import prepare,summarize
from tracker.schema import InputError,digest
from tracker.jev import validate_answers,DEFAULT_MODEL,SELECTION_POLICY


class PlanCorpusTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.source=self.root/'source';self.source.mkdir()
        self.docs=[document(),document()];self.docs[1]['metadata']['annotator']='Fixture B'
        (self.source/'allocation.json').write_text(json.dumps({'development':['synthetic'],'reserved':['unread']}),encoding='utf-8')
        self.save()
        self.mock=patch('research.plan_corpus.build',return_value=({'source_revision':'synthetic-test'},None))
        self.mock.start();self.addCleanup(self.mock.stop)

    def save(self):
        for folder,doc in zip(('v0_human_1','v0_human_2'),self.docs):
            path=self.source/'upstream/data'/folder;path.mkdir(parents=True,exist_ok=True)
            (path/'synthetic.json').write_text(json.dumps(doc),encoding='utf-8')
            (path/'unread.json').write_text('INVALID RESERVED DATA MUST NOT BE READ',encoding='utf-8')

    def read(self,path):return json.loads(path.read_text(encoding='utf-8'))

    def test_sample_and_requests_do_not_depend_on_labels_edges_or_annotator_identity(self):
        a=self.root/'a';b=self.root/'b';prepare(self.source,a,per_trace=2)
        for doc in self.docs:
            doc['edges']=[];doc['metadata']['annotator']='different'
            for node in doc['nodes']:node['label']='planning' if node['source']=='response' else 'context'
        self.save();prepare(self.source,b,per_trace=2)
        def visible(root):return [(c['case_id'],c['requests']) for c in self.read(root/'cases.json')]
        self.assertEqual(visible(a),visible(b));self.assertEqual(len(visible(a)),2)
        with self.assertRaises(InputError):prepare(self.source,a)

    def test_full_inventory_covers_final_unit_and_each_request_stops_at_its_own_span(self):
        out=self.root/'all';result=prepare(self.source,out,per_trace=40)
        self.assertEqual((result['inventory'],result['cases']),(4,4))
        cases=self.read(out/'cases.json');raw=self.docs[0]['raw_text']
        for case in cases:
            state=case['requests']['source_time']['state'];unit=state['source'];prefix=state['prefix']
            self.assertEqual(prefix[0]['text'],raw['question'])
            self.assertEqual(prefix[-1]['text'],raw['response'][:unit['end']])
            self.assertEqual(prefix[-1]['text'][unit['start']:unit['end']],unit['text'])
            self.assertNotIn('native_reference',state);self.assertNotIn('subject',state)
        self.assertEqual(cases[-1]['requests']['source_time']['state']['source']['end'],len(raw['response']))

    def test_native_disagreement_and_missing_predictions_never_become_product_references(self):
        self.docs[1]['nodes'][2]['label']='reflection';self.save()
        out=self.root/'pack';prepare(self.source,out,per_trace=40)
        cases=self.read(out/'cases.json');rows=[]
        for i,case in enumerate(cases[:3]):
            request=case['requests']['source_time']
            answers=validate_answers({'answers':{'source_plan':{'type':'choice','probabilities':{'present':.34,'absent':.33,'unresolved':.33}}}},request)
            row={'case_id':case['case_id'],'variant':'source_time','set':'development','model':DEFAULT_MODEL,
                 'selection_policy':SELECTION_POLICY,'request_hash':digest(request),'answers':answers,'usage':{'input_tokens':10}}
            if i==0:row['reuse_basis']='Synthetic exact-request reuse'
            rows.append(row)
        (out/'source_time-development.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows),encoding='utf-8')
        report=summarize(out);counts=report['counts']['all']
        self.assertEqual((report['completed'],report['planned']),(3,4))
        self.assertEqual((counts['native_reference_unresolved'],counts['native_scored']),(1,2))
        self.assertEqual((report['reused_results'],report['new_provider_calls'],report['new_usage']['input_tokens']),(1,2,20))
        self.assertEqual(report['independent_product_references'],0);self.assertIsNone(report['product_accuracy'])
        inventory=self.read(out/'inventory.json');inventory.pop()
        (out/'inventory.json').write_text(json.dumps(inventory),encoding='utf-8')
        with self.assertRaises(InputError):summarize(out)


if __name__=='__main__':unittest.main()
