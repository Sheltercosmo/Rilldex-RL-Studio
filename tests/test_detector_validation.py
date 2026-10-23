"""Authored reference judgments test workflow correctness, not detector accuracy."""
from copy import deepcopy
import json
import unittest
from urllib.request import Request,urlopen

from tracker import detector_validation as v, measurement_reviews as review
from tracker.schema import InputError
import test_condition_reviews as fixtures


class ValidationTests(unittest.TestCase):
    setUp=fixtures.ConditionReviewTests.setUp
    add=fixtures.ConditionReviewTests.add
    detector=fixtures.ConditionReviewTests.detector
    check=staticmethod(fixtures.ConditionReviewTests.check)
    sample=fixtures.ConditionReviewTests.sample
    judgment=fixtures.ConditionReviewTests.judgment

    def reference(self):
        runs=[self.add('positive'),self.add('negative',passed=True),self.add('unresolved',complete=False)]
        model=self.detector();model.run(self.check);sample=self.sample(model,runs)
        labels={runs[0]['id']:'taken',runs[1]['id']:'not_taken',runs[2]['id']:'taken'}
        for case in sample['cases']:review.receive(self.store,self.judgment(sample,case['id'],labels[case['run_id']]))
        body=dict(name='Delivery checks',sample_ids=[sample['id']],reviewer='Control reviewer',seed='trial',held_out_percent=0)
        return model,sample,body,v.create(self.store,body)

    def test_frozen_labels_versions_missing_coverage_and_comparison(self):
        model,sample,body,reference=self.reference()
        first=v.capture(self.store,dict(set_id=reference['id'],split='development',monitor_id=model.id))
        self.assertEqual(first['report']['coverage'],2/3)
        self.assertEqual(first['report']['agreement'],1)
        self.assertEqual(first['report']['positive_detection_coverage'],.5)
        cid=sample['cases'][0]['id'];old=review.case_view(self.store,sample['id'],cid,'Control reviewer')['annotation']
        revised=self.judgment(sample,cid,'unknown');revised['supersedes']=old['id'];review.receive(self.store,revised)
        self.assertEqual(v.load(self.store,reference['id']),reference)
        self.assertNotEqual(v.create(self.store,body)['id'],reference['id'])
        def changed(ctx):return {'status':'flagged','summary':'Authored false-positive control','input_evidence':['reward','passed']}
        other=self.detector(version='2');other.run(changed)
        second=v.capture(self.store,dict(set_id=reference['id'],split='development',monitor_id=other.id))
        comparison=v.compare(self.store,first['id'],second['id'])
        self.assertEqual(comparison['counts']['regressed'],1)
        self.assertEqual(second['report']['counts']['false_positive'],1)
        self.assertEqual(v.load(self.store,first['id'],True),first)

    def test_local_callbacks_do_not_receive_references_and_keep_errors(self):
        _,_,_,reference=self.reference();seen=[]
        def check(case):
            self.assertNotIn('label',case);self.assertNotIn('reference',case);self.assertNotIn('prediction',case)
            seen.append(case['id'])
            if case['run_id']=='run-negative':raise RuntimeError('Authored test error')
            return True
        result=v.ValidationSet(self.db,reference['id']).evaluate(check,name='Local check',version='v2')
        self.assertEqual(len(seen),3);self.assertEqual(result['report']['counts']['error'],1)
        self.assertEqual(result['report']['coverage'],2/3)
        self.assertEqual(result['report']['positive_detection_coverage'],1)
        no_results=v.publish(self.store,dict(set_id=reference['id'],split='development',detector={'name':'Unrun','version':'1'},predictions=[]))
        self.assertIsNone(no_results['report']['agreement']);self.assertEqual(no_results['report']['coverage'],0)
        self.assertEqual(no_results['report']['counts']['missing'],3)
        seen.clear()
        with self.assertRaisesRegex(InputError,'explicit version'):
            v.ValidationSet(self.db,reference['id']).evaluate(check,name='Local check',version='')
        self.assertEqual(seen,[])

    def test_split_grouping_duplicates_compatibility_and_empty_split(self):
        model,sample,body,reference=self.reference()
        again=self.sample(model,[self.add('positive'),self.add('negative',passed=True),self.add('unresolved',complete=False)])
        self.assertEqual(again['id'],sample['id'])
        held=v.create(self.store,{**body,'held_out_percent':100})
        self.assertTrue(all(c['split']=='held_out' for c in held['cases']))
        with self.assertRaisesRegex(InputError,'no labeled'):v.capture(self.store,dict(set_id=held['id'],split='development',monitor_id=model.id))
        wrong=self.detector(version='other',description='A different condition')
        with self.assertRaisesRegex(InputError,'question'):v.capture(self.store,dict(set_id=reference['id'],split='development',monitor_id=wrong.id))
        response=v.capture(self.store,dict(set_id=reference['id'],split='development',monitor_id=model.id))
        other=v.capture(self.store,dict(set_id=held['id'],split='held_out',monitor_id=model.id))
        with self.assertRaisesRegex(InputError,'same frozen'):v.compare(self.store,response['id'],other['id'])
        listing=v.listing(self.store);self.assertEqual(len(listing['sets']),2);self.assertNotIn('rows',listing['results'][0]['report'])

    def test_changed_external_inputs_are_not_silently_scored(self):
        model,_,_,reference=self.reference()
        changed=self.detector(version='paths-v2',inputs={'reward':'/raw/components/completion','passed':'/raw/components/constraint'})
        changed.run(self.check)
        result=v.capture(self.store,dict(set_id=reference['id'],split='development',monitor_id=changed.id))
        self.assertEqual(result['report']['counts']['changed_inputs'],3)
        self.assertEqual(result['report']['coverage'],0)

    def test_reference_detail_and_strict_submission(self):
        _,_,_,reference=self.reference();case=reference['cases'][0]
        detail=v.case_view(self.store,reference['id'],case['id']);self.assertEqual(detail['reference'],case['label'])
        self.assertTrue(detail['source_events']);self.assertIn('&case=',detail['review_url'])
        base=dict(set_id=reference['id'],split='development',detector={'name':'Check','version':'1'})
        for predictions in ([{'case_id':'foreign','value':False}], [{'case_id':case['id'],'value':'false'}],
                            [{'case_id':case['id'],'value':False}]*2):
            with self.assertRaises(InputError):v.publish(self.store,{**base,'predictions':predictions})

    def test_unresolved_reference_and_scope_do_not_inflate_accuracy(self):
        _,_,_,reference=self.reference()
        cases=deepcopy(reference['cases'])
        cases[0]['label']['label']='unknown'
        cases[1]['label']['label']='not_opportunity'
        cases[2]['label']['label']='taken'
        predictions={c['id']:dict(value=False,status='decided',reason='Authored control') for c in cases}
        predictions[cases[2]['id']].update(value=None,status='error')
        report=v.report(cases,predictions)
        self.assertIsNone(report['agreement'])
        self.assertEqual(report['coverage'],0)
        self.assertEqual(report['positive_detection_coverage'],0)
        self.assertEqual(report['counts']['reference_unknown'],1)
        self.assertEqual(report['counts']['scope_disagreement'],1)
        self.assertEqual(report['counts']['prediction_unavailable'],1)

    def test_builtin_diagnostic_review_uses_full_saved_source(self):
        from pathlib import Path
        from tracker import diagnostic_monitors as diagnostic,monitoring
        import test_diagnostic_monitors as fixture
        run=self.add('native')
        source=diagnostic.from_run(run);folder=Path(self.db).parent/'decisions'
        prediction=diagnostic.execute(source,folder,fixture.transport)
        registered=diagnostic.register(self.store,run,source,prediction,folder)
        monitor=monitoring.create(self.store,dict(name='Answer search',kind='metric',observer=registered['observer'],metric='diagnostic_online_reference_search'))
        monitoring.sync(self.store)
        sample=review.create(self.store,dict(monitor_id=monitor['id'],run_ids=[run['id']],size=10,seed='native'))
        case=review.case_view(self.store,sample['id'],sample['cases'][0]['id'])
        self.assertEqual(case['review_kind'],'rollout_condition');self.assertEqual(len(case['source_events']),len(run['events']))
        event=next(e for e in case['source_events'] if e['text'])
        label=self.judgment(sample,case['case_id'],'not_taken',citations=[dict(event_id=event['id'],start=0,end=len(event['text']))])
        review.receive(self.store,label)
        frozen=v.create(self.store,dict(name='Native diagnostic',sample_ids=[sample['id']],reviewer='Control reviewer',seed='native',held_out_percent=0))
        result=v.capture(self.store,dict(set_id=frozen['id'],split='all',monitor_id=monitor['id']))
        self.assertEqual(result['report']['counts']['true_negative'],1)

    def test_opportunity_frames_and_task_split_are_preserved(self):
        import test_measurement_reviews as fixture
        source=fixture.MeasurementReviewTests();source.setUp();self.addCleanup(source.doCleanups)
        sample=review.create(source.store,source.request)
        for case in sample['cases']:review.receive(source.store,source.label(sample,case['id']))
        frozen=v.create(source.store,dict(name='Opportunity checks',sample_ids=[sample['id']],reviewer='Reviewer A',seed='groups',held_out_percent=50))
        result=v.capture(source.store,dict(set_id=frozen['id'],split='all',monitor_id=source.monitor['id']))
        self.assertEqual(result['report']['counts']['cases'],len(frozen['cases']))
        splits={}
        for case in frozen['cases']:splits.setdefault(tuple(case['split_group']),set()).add(case['split'])
        self.assertTrue(all(len(s)==1 for s in splits.values()))
        context=v.case_input(source.store,frozen,frozen['cases'][0])
        self.assertNotIn('run',context);self.assertTrue(context['source_events'])


class ValidationHTTPTests(unittest.TestCase):
    setUp=ValidationTests.setUp
    add=ValidationTests.add
    detector=ValidationTests.detector
    check=staticmethod(ValidationTests.check)
    sample=ValidationTests.sample
    judgment=ValidationTests.judgment
    reference=ValidationTests.reference
    def test_http_routes(self):
        import test_generation_cohort_transport as transport
        self.stop_server=transport.GenerationCohortTransportTests.stop_server
        model,sample,body,reference=self.reference()
        endpoint=transport.GenerationCohortTransportTests.start_server(self)
        def call(path,data=None):
            req=Request(endpoint+path,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json'})
            with urlopen(req,timeout=20) as response:return json.load(response)
        self.assertEqual(call('/api/detector-validation/sets',body)['id'],reference['id'])
        result=call('/api/detector-validation/capture',dict(set_id=reference['id'],split='development',monitor_id=model.id))
        self.assertEqual(call('/api/detector-validation/results/'+result['id']),result)
        self.assertEqual(call('/api/detector-validation/sets/'+reference['id']+'?case='+reference['cases'][0]['id'])['reference'],reference['cases'][0]['label'])
        self.assertEqual(call('/api/detector-validation/compare?left='+result['id']+'&right='+result['id'])['counts']['unchanged'],3)


if __name__=='__main__':unittest.main()
