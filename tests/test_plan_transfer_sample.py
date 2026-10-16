from copy import deepcopy
import json
import tempfile
from pathlib import Path
import unittest

from tracker.adapters import normalize
from tracker.activity import units
from tracker.schema import InputError,digest
from research.plan_transfer_sample import build,review_case,summarize,VERSION
from research.relation_scope import rollout_source_evidence,rollout_evidence
from research.relation_review import evaluate


def run():
    return normalize({'schema_version':'ATIF-v1.7','agent':{'name':'test'},'steps':[
        {'step_id':0,'source':'user','message':'Check the supplied values.'},
        *[{'step_id':i+1,'source':'agent','message':f'🧭 Recorded expression {i}. Another clause {i}.'} for i in range(9)]]})[0]


class TransferSampleTests(unittest.TestCase):
    def setUp(self):
        self.run=run();self.dimensions={self.run['id']:{'domain':'fixture','family':'synthetic_test'}}

    def test_selection_covers_text_position_and_is_independent_of_observation_labels(self):
        m,cases,inventory=build([self.run],self.dimensions)
        self.assertEqual(len(cases),6);self.assertEqual(len(inventory),18)
        self.assertEqual(sorted(c['position'] for c in cases),['early','early','late','late','middle','middle'])
        changed=deepcopy(self.run);changed['outcome']={'reward':'not a selection variable'}
        changed['raw']['hidden_labels']=['present'];changed['metadata']['checkpoint']='different-metadata'
        _,other,_=build([changed],self.dimensions)
        self.assertEqual([(c['case_id'],c['requests']) for c in cases],[(c['case_id'],c['requests']) for c in other])
        self.assertEqual(m['variants'],['local'])

    def test_every_request_and_blind_case_retains_its_source_cutoff(self):
        _,cases,_=build([self.run],self.dimensions)
        for c in cases:
            state=c['requests']['local']['state'];source=state['source'];prefix=state['prefix']
            self.assertEqual(max(e['event_index'] for e in prefix),source['event_index'])
            self.assertEqual(len(prefix[-1]['text']),source['end'])
            self.assertEqual(prefix[-1]['text'][source['start']:source['end']],source['text'])
            blind=review_case(c);self.assertEqual(blind['subject']['text'],source['text'])
            self.assertEqual(blind['fields'],c['requests']['local']['questions'])
            self.assertNotIn('outcome',blind['inspector_state'])

    def test_direct_source_projection_preserves_existing_pair_evidence(self):
        candidates=[u for u in units(self.run) if u['eligible']]
        records,source,subject=rollout_evidence(self.run,candidates[0]['id'],candidates[2]['id'])
        direct,end=rollout_source_evidence(self.run,candidates[2]['id'])
        self.assertEqual((records,subject),(direct,end));self.assertNotEqual(source,subject)
        with self.assertRaises(InputError):rollout_source_evidence(self.run,'missing')

    def test_no_visible_text_or_mismatched_source_inventory_is_rejected(self):
        with self.assertRaises(InputError):build([],self.dimensions)
        with self.assertRaises(InputError):build([self.run,self.run],self.dimensions)
        with self.assertRaises(InputError):build([self.run],self.dimensions,per_position=True)
        empty=deepcopy(self.run);empty['events']=[e for e in empty['events'] if e['kind']=='instruction']
        with self.assertRaises(InputError):build([empty],self.dimensions)

    def test_transport_failures_remain_unobserved_and_bound_to_the_exact_request(self):
        m,cases,inventory=build([self.run],self.dimensions)
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary)
            blind={'version':VERSION,'manifest_hash':digest(m),'cases':[review_case(c) for c in cases]}
            for name,data in [('manifest',m),('cases',cases),('inventory',inventory),('blind-cases',blind)]:
                (folder/(name+'.json')).write_text(json.dumps(data),encoding='utf-8')
            row={'case_id':cases[0]['case_id'],'request_hash':digest(cases[0]['requests']['local']),
                 'http_status':400,'provider_error_type':'max_tokens_exceeded'}
            path=folder/'execution-errors.jsonl';path.write_text(json.dumps(row)+'\n',encoding='utf-8')
            summary=summarize(folder)
            self.assertEqual((summary['observed'],summary['failed'],summary['unobserved_without_failure_receipt']),(0,1,5))
            self.assertEqual(summary['by_domain']['fixture']['choices'],{})
            report=evaluate(folder);self.assertEqual(report['by_profile'],{})
            case=report['inspection']['cases'][0]
            self.assertEqual(case['execution']['execution'],'failed')
            self.assertTrue(any(f['kind']=='inference_failed' for f in case['findings']))
            self.assertEqual(case['fields'][0]['prediction']['status'],'unobserved')
            for bad in [{**row,'request_hash':'wrong'},{**row,'http_status':200},
                        {**row,'case_id':'unknown'},{**row,'provider_error_type':[]}]:
                path.write_text(json.dumps(bad)+'\n',encoding='utf-8')
                with self.assertRaises(InputError):summarize(folder)
            path.write_text((json.dumps(row)+'\n')*2,encoding='utf-8')
            with self.assertRaises(InputError):summarize(folder)


if __name__=='__main__':unittest.main()
