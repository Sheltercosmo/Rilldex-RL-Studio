from copy import deepcopy
import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch

from tracker.schema import digest,InputError
from tracker.jev import validate_answers,SELECTION_POLICY
from tracker.prefix_encoding import expand,compact
from research.prefix_encoding_study import prepare,validate_cases,summarize,schedule,review_case
from research.relation_review import evidence,evaluate
from test_plan_transfer_sample import run as sample_run
from research.plan_transfer_sample import build,review_case as parent_case,VERSION as PARENT_VERSION


def fixture(root):
    run=sample_run()
    # Distinct event occurrences with long identical text; no source labels.
    for e in run['events']:
        if e['kind']=='model_text':e['text']='I will inspect the recorded evidence. '+('Recorded context. '*180)
    # Adapters retain model messages as expression events.
    models=[e for e in run['events'] if e['kind'] not in {'instruction','context'}]
    for e in models:e['text']='I will inspect the recorded evidence. '+('Recorded context. '*180)
    m,cases,inventory=build([run],{run['id']:{'domain':'synthetic','family':'test'}})
    parent=root/'parent';parent.mkdir()
    blind={'version':PARENT_VERSION,'manifest_hash':digest(m),'cases':[parent_case(c) for c in cases]}
    for name,value in [('manifest',m),('cases',cases),('inventory',inventory),('blind-cases',blind)]:
        (parent/(name+'.json')).write_text(json.dumps(value),encoding='utf-8')
    rows=[]
    for c in cases[:-1]:
        req=c['requests']['local'];answers=validate_answers({'answers':{'source_plan':{'type':'choice',
            'choice':'absent','confidence':0,'probabilities':{'present':.34,'absent':.33,'unresolved':.33}}}},req)
        for a in answers.values():a.pop('evidence',None)
        rows.append({'case_id':c['case_id'],'variant':'local','set':'development','request_hash':digest(req),
                     'selection_policy':SELECTION_POLICY,'model':m['model'],'answers':answers})
    (parent/'local-development.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows),encoding='utf-8')
    output=root/'study';prepare(parent,output);return output


class PrefixStudyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder=fixture(Path(self.temp.name))
        self.m=json.loads((self.folder/'manifest.json').read_text(encoding='utf-8'))
        self.cases=json.loads((self.folder/'cases.json').read_text(encoding='utf-8'))

    def test_only_changed_requests_are_scheduled_and_missing_baselines_are_not_retried(self):
        self.assertEqual(self.m['planned_calls'],schedule(self.cases))
        for c in self.cases:
            changed=c['requests']['baseline']!=c['requests']['compact']
            calls=[r['variant'] for r in self.m['planned_calls'] if r['case_id']==c['case_id']]
            self.assertEqual(calls,(['repeat'] if c['baseline_observed'] else [])+['compact'] if changed else [])
            self.assertEqual(expand(c['requests']['compact']),c['requests']['baseline'])
        with self.assertRaises(InputError):prepare(self.folder.parent/'parent',self.folder)

    def test_reports_bind_actual_encoded_packet_and_expanded_review_text(self):
        _,_,reviewed,_,_=evidence(self.folder,'compact')
        for original,c in zip(self.cases,reviewed):
            self.assertEqual(c['inspector_state']['prefix'],original['requests']['compact']['state']['prefix'])
            self.assertTrue(all(isinstance(e['text'],str) for e in c['available_prefix']))
            self.assertNotIn('answers',c)
        changed=next(c for c in self.cases if c['requests']['baseline']!=c['requests']['compact'])
        self.assertNotEqual(review_case(changed,'baseline')['case_hash'],review_case(changed,'compact')['case_hash'])
        report=evaluate(self.folder,variant='compact');self.assertEqual(report['by_profile'],{})
        item=next(c for c in report['inspection']['cases'] if c['case_id']==changed['case_id'])
        self.assertIn('evidence_encoding',item['profile']);self.assertEqual(len(item['observer_comparison']),3)
        self.assertEqual(item['encoding_audit']['omitted_events'],0)

    def test_changed_questions_schedule_or_error_binding_is_rejected(self):
        bad=deepcopy(self.cases);bad[0]['requests']['compact']['questions']['source_plan']['criteria']['present']='changed'
        with self.assertRaises(InputError):validate_cases(self.m,bad)
        m=deepcopy(self.m);m['planned_calls']=[]
        with self.assertRaises(InputError):validate_cases(m,self.cases)
        row={**self.m['planned_calls'][0],'request_hash':'wrong','http_status':400}
        (self.folder/'errors.jsonl').write_text(json.dumps(row)+'\n',encoding='utf-8')
        with self.assertRaises(InputError):summarize(self.folder)

    def test_noop_reuse_is_not_counted_as_fresh_comparison_or_cost(self):
        s=summarize(self.folder)
        self.assertEqual(s['counts'].get('fresh_successes',0),0)
        self.assertEqual(s['counts'].get('paired_fresh_comparisons',0),0)
        self.assertEqual(s['new_usage'],{})
        self.assertEqual(s['completed']['baseline'],len(self.cases)-1)


if __name__=='__main__':unittest.main()
