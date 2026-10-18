"""Authored control judgments exercise the review loop, not real detector accuracy."""
from copy import deepcopy
import unittest

from tracker import measurement_reviews as review, investigation_workspace
from tracker.schema import InputError
import test_reward_detectors as fixture
import test_monitor_evaluation_inputs as evaluation_fixture


class ConditionReviewTests(unittest.TestCase):
    setUp=fixture.RewardDetectorTests.setUp
    add=fixture.RewardDetectorTests.add
    detector=fixture.RewardDetectorTests.detector
    check=staticmethod(fixture.RewardDetectorTests.check)
    evaluation_detector=evaluation_fixture.EvaluationInputTests.detector
    record=evaluation_fixture.EvaluationInputTests.record
    detect=staticmethod(evaluation_fixture.EvaluationInputTests.detect)

    def sample(self, monitor, runs):
        return review.create(self.store,dict(monitor_id=monitor.id,run_ids=[r['id'] for r in runs],size=100,seed='authored-controls'))

    def judgment(self,sample,cid,label='taken',citations=None,reviewer='Control reviewer'):
        case=review.case_view(self.store,sample['id'],cid,reviewer)
        return dict(sample_id=sample['id'],case_id=cid,reviewer=reviewer,reviewer_role='developer_review',label=label,
            note='Authored review control; not independent accuracy evidence.',citations=citations or [{'input_name':'passed'}],
            supersedes=(case['annotation'] or {}).get('id'))

    def test_all_results_sampled_with_missing_results_counted_and_no_output_leak(self):
        runs=[self.add('flag'),self.add('clear',passed=True),self.add('unknown',complete=False),self.add('outside',definition='delivery/v4')]
        monitor=self.detector();monitor.run(self.check)
        runs.append(self.add('waiting'))
        sample=self.sample(monitor,runs);raw=review.load(self.store,sample['id'])
        self.assertEqual(sample['frame_cases'],4);self.assertEqual(sample['runs_without_case_frame'],['run-waiting'])
        self.assertEqual([sum(r['prediction'] is v for r in raw['frame']) for v in (True,False,None)],[1,1,2])
        self.assertEqual(self.sample(monitor,runs[::-1])['id'],sample['id'])
        for row in raw['frame']:
            case=review.case_view(self.store,sample['id'],row['id'])
            for key in ('prediction','predicted_scope','measurement_id','feedback','result','details'):
                self.assertNotIn(key,case)
            self.assertEqual(len(case['source_events']),len(runs[0]['events']))
            self.assertEqual({r['name'] for r in case['declared_inputs']},{'reward','passed','@reward_definition'})
        cid=next(r['id'] for r in raw['frame'] if r['run_id']=='run-unknown')
        missing=next(r for r in review.case_view(self.store,sample['id'],cid)['declared_inputs'] if r['name']=='passed')
        self.assertFalse(missing['present']);self.assertNotIn('value',missing)

    def test_false_positives_misses_scope_and_unresolved_remain_separate(self):
        runs=[self.add('flag'),self.add('clear',passed=True),self.add('unknown',complete=False),self.add('outside',definition='delivery/v4')]
        monitor=self.detector();monitor.run(self.check);sample=self.sample(monitor,runs)
        rows={r['run_id']:r for r in review.load(self.store,sample['id'])['frame']}
        for rid,label in [('run-flag','not_taken'),('run-clear','taken'),('run-unknown','taken'),('run-outside','not_opportunity')]:
            result=review.receive(self.store,self.judgment(sample,rows[rid]['id'],label))
            self.assertIn('prediction',result['case'])
            self.assertNotIn('prediction',review.case_view(self.store,sample['id'],rows[rid]['id'],'Other reviewer'))
        stats=review.public(self.store,sample['id'])['reviewers'][0]
        self.assertEqual((stats['false_positive'],stats['false_negative'],stats['comparable'],stats['agreement']),(1,1,2,0))
        self.assertEqual(stats['scope_agreements'],1);self.assertEqual(stats.get('eligibility_disputes',0),0)
        self.assertEqual(stats['prediction_unknown_with_decidable_reference'],1)
        audit=investigation_workspace.audit_summary(self.store,monitor.id,set(sample['measurement_ids']))[0]
        self.assertEqual((audit['scope_agreements'],audit['disagree'],audit['unresolved']),(1,2,1))

    def test_citations_are_checked_original_inputs_and_support_revisions(self):
        run=self.add('flag');monitor=self.detector();monitor.run(self.check);sample=self.sample(monitor,[run]);cid=sample['cases'][0]['id']
        for refs in [[{'input_name':'undeclared'}],[{'evaluation_id':'foreign'}],[{'evaluator_input':'foreign'}],[{'event_id':[],'start':0,'end':1}],
                     [{'input_name':'passed','value':True}],[{'input_name':'passed'},{'input_name':'passed'}]]:
            with self.subTest(refs=refs),self.assertRaises(InputError):review.receive(self.store,self.judgment(sample,cid,citations=refs))
        first=self.judgment(sample,cid);saved=review.receive(self.store,first)
        self.assertEqual(review.receive(self.store,first)['annotation_id'],saved['annotation_id'])
        citation=saved['case']['annotation']['citations'][0]
        self.assertIs(citation['input']['value'],False)
        second=self.judgment(sample,cid,'unknown');review.receive(self.store,second)
        with self.assertRaisesRegex(InputError,'reload'):review.receive(self.store,{**first,'note':'Stale edit'})
        self.assertEqual(review.case_view(self.store,sample['id'],cid,'Control reviewer')['annotation']['label'],'unknown')

    def test_all_pinned_evaluators_are_reviewable_not_only_cited_reports(self):
        run=self.add('flag');monitor=self.evaluation_detector();left=self.record(run);right=self.record(run,'independent_check','failed')
        def subset(ctx):
            result=self.detect(ctx);result['evaluation_ids']=[left['id']];return result
        monitor.run(subset);sample=self.sample(monitor,[run]);cid=sample['cases'][0]['id']
        case=review.case_view(self.store,sample['id'],cid)
        self.assertEqual({r['id'] for r in case['evaluator_reports']},{left['id'],right['id']})
        label=self.judgment(sample,cid,citations=[{'evaluation_id':right['id']}])
        self.assertIn('report_hash',review.receive(self.store,label)['case']['annotation']['citations'][0])
        old=deepcopy(review.load(self.store,sample['id']))
        late=self.record(run,'independent_check','passed',performed_at='2026-10-18T12:00:00Z')
        self.assertEqual(review.load(self.store,sample['id']),old)
        with self.assertRaisesRegex(InputError,'current saved results'):self.sample(monitor,[run])
        case=review.case_view(self.store,sample['id'],cid)
        self.assertFalse(case['freshness']['current_input'])
        self.assertNotIn(late['id'],[r['id'] for r in case['evaluator_reports']])
        with self.assertRaisesRegex(InputError,'outside'):review.receive(self.store,self.judgment(sample,cid,citations=[{'evaluation_id':late['id']}]))
        monitor.run(self.detect);new=self.sample(monitor,[run])
        self.assertNotEqual(sample['id'],new['id'])
        self.assertEqual(len(review.case_view(self.store,new['id'],new['cases'][0]['id'])['evaluator_reports']),3)

    def test_empty_evaluator_selection_is_citable_without_inventing_source_evidence(self):
        run=self.add('unknown');monitor=self.evaluation_detector();monitor.run(self.detect);sample=self.sample(monitor,[run]);cid=sample['cases'][0]['id']
        case=review.case_view(self.store,sample['id'],cid)
        self.assertEqual(case['evaluator_inputs'],{'check':[],'reward':[]})
        result=review.receive(self.store,self.judgment(sample,cid,'unknown',citations=[{'evaluator_input':'check'}]))
        self.assertEqual(result['case']['annotation']['citations'][0]['evaluation_ids'],[])

    def test_reward_version_is_visible_and_unresolved_scope_is_not_a_disagreement(self):
        a=self.add('outside',definition='delivery/v4');b=self.add('unknown',complete=False)
        monitor=self.detector();monitor.run(self.check);sample=self.sample(monitor,[a,b])
        rows={r['run_id']:r for r in review.load(self.store,sample['id'])['frame']}
        case=review.case_view(self.store,sample['id'],rows[a['id']]['id'])
        self.assertEqual(next(r['value'] for r in case['declared_inputs'] if r['name']=='@reward_definition'),'delivery/v4')
        review.receive(self.store,self.judgment(sample,rows[a['id']]['id'],'taken',citations=[{'input_name':'@reward_definition'}]))
        review.receive(self.store,self.judgment(sample,rows[b['id']]['id'],'not_opportunity'))
        stats=review.public(self.store,sample['id'])['reviewers'][0]
        self.assertEqual((stats['eligibility_disputes'],stats['scope_unresolved'],stats['prediction_unknown_with_decidable_reference']),(1,1,1))

    def test_generic_binary_monitor_review_includes_worker_errors(self):
        from tracker.workspace_analysis import Workspace
        a=self.add('a');b=self.add('b')
        monitor=Workspace(self.db,observer='source',experiment='train').monitor('Custom rule',version='1',description='Authored binary check',unit='fraction',aggregation='incidence')
        def measure(ctx):
            if ctx.run['id']==b['id']:raise RuntimeError('Authored unavailable dependency')
            return {'value':0}
        self.assertEqual(monitor.run(measure)['errors'],1)
        sample=self.sample(monitor,[a,b]);self.assertEqual(sample['sample_size'],2)
        row=next(r for r in review.load(self.store,sample['id'])['frame'] if r['run_id']==b['id'])
        self.assertIsNone(row['prediction'])
        case=review.case_view(self.store,sample['id'],row['id']);event=next(e for e in case['source_events'] if e['text'])
        result=review.receive(self.store,self.judgment(sample,row['id'],'unknown',citations=[dict(event_id=event['id'],start=0,end=len(event['text']))]))
        self.assertEqual(result['sample']['reviewers'][0]['reference_unknown'],1)


if __name__=='__main__':unittest.main()
