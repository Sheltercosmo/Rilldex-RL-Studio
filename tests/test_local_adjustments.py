from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from tracker import local_adjustments as la
from tracker.schema import digest,InputError,event
from tracker.semantic_extraction import Pipeline
from research.local_adjustment_trial import control
from research.attempt_revision_trial import CASES


class LocalAdjustmentTests(TestCase):
    def test_using_a_prior_correction_does_not_create_a_correction_attempt(self):
        for declaration in ['commits','proposes','reports_finished','defers','withdraws','reports_blocked']:
            self.assertFalse(la.prospective({'selection':'uses_prior_adjustment','declaration':declaration}))
            self.assertEqual(la.prospective({'selection':'performs_adjustment','declaration':declaration}),declaration in {'commits','proposes'})
        v=control(CASES[0]);req=la.make_request(v['run'],v['unit'],v['items'],la.EFFECT_VERSION)
        self.assertEqual(req['state']['items'],v['items'])
        self.assertIn(v['items'][0]['work'],req['questions']['w1']['instructions'])
        event(v['run']['events'],kind='message',actor='agent',trajectory_id=v['unit']['trajectory_id'],pointer='/future',text='FUTURE_RESULT')
        self.assertEqual(la.make_request(v['run'],v['unit'],v['items'],la.EFFECT_VERSION),req)

    def test_facet_cannot_replace_declaration_or_turn_report_into_future_adjustment(self):
        from tracker.semantic_extraction import read
        root=Path(__file__).resolve().parents[1]/'research/local-adjustments-v2-2026-10-08/software'
        b=read(root/'baseline.json');before=deepcopy(b['local'])
        def decide(req):
            return ({k:{'value':'adjustment_content'} for k in req['questions']},digest(req))
        r=la.build(b['run'],b['document'],b['local'],decide,la.FACET_VERSION)
        expected={(o['unit_id'],i['id']):i['declaration'] for o in before['observations'] for i in o['items']}
        for o in r['observations']:
            for i in o['items']:
                self.assertEqual(i['declaration'],expected[o['unit_id'],i['item_id']])
                if i['declaration']=='reports_finished':self.assertFalse(la.prospective(i))
        self.assertEqual(before,b['local'])

    def test_facet_preserves_attribution_and_has_no_reclassification_options(self):
        v=control(CASES[0]);v['items'][0]['declaration']='reports_finished'
        r=la.make_request(v['run'],v['unit'],v['items'],la.FACET_VERSION)
        self.assertEqual(r['state']['items'][0]['declaration'],'reports_finished')
        self.assertEqual(set(r['questions']['w1']['criteria']),set(la.FACET_CHOICES))
        self.assertFalse({'prospective_adjustment','ordinary_work','state_report'}&set(r['questions']['w1']['criteria']))
        v['items'][0]['declaration']='invented'
        with self.assertRaises(InputError):la.make_request(v['run'],v['unit'],v['items'],la.FACET_VERSION)

    def test_budget_interrupt_resume_and_read_only_audit(self):
        from tracker import work_item_pass
        source=Path(__file__).resolve().parents[1]/'research/work-items-complete-2026-10-08/software'
        calls=[]
        def transport(r):
            calls.append(digest(r))
            return {'model':r['model'],'answers':{k:{'type':'choice','choice':'ordinary_work',
                'probabilities':{x:float(x=='ordinary_work') for x in q['criteria']}} for k,q in r['questions'].items()}}
        with TemporaryDirectory() as folder:
            with self.assertRaisesRegex(InputError,'budget exhausted'):
                work_item_pass.adjustments(source,transport,adjustment_directory=folder,max_calls=1)
            self.assertEqual(len(calls),1)
            self.assertFalse((Path(folder)/'local-adjustments.json').exists())
            resumed=work_item_pass.adjustments(source,transport,adjustment_directory=folder,max_calls=34)
            self.assertEqual(resumed['new_calls'],34)
            self.assertEqual(len(calls),35);self.assertEqual(len(set(calls)),35)
            cached=work_item_pass.adjustments(source,transport,adjustment_directory=folder,max_calls=0)
            audited=work_item_pass.adjustments(source,transport,adjustment_directory=folder,max_calls=0,audit_only=True)
            self.assertEqual(cached['new_calls'],0);self.assertEqual(audited['new_calls'],0)
            self.assertEqual(audited['validation']['items'],60);self.assertEqual(len(calls),35)

    def test_future_append_does_not_change_local_request_identity(self):
        v=control(CASES[0]);run=v['run'];req=la.make_request(run,v['unit'],v['items'])
        event(run['events'],kind='feedback',actor='environment',trajectory_id=v['unit']['trajectory_id'],pointer='/future',text='FUTURE_SENTINEL')
        self.assertEqual(la.make_request(run,v['unit'],v['items']),req)
        self.assertNotIn('WITHHELD_FUTURE_RESULT',str(req));self.assertNotIn('FUTURE_SENTINEL',str(req))

    def test_changed_source_or_work_content_invalidates_request(self):
        v=control(CASES[0]);req=la.make_request(v['run'],v['unit'],v['items'])
        v['items'][0]['work']='A different selected work scope'
        self.assertNotEqual(digest(req),digest(la.make_request(v['run'],v['unit'],v['items'])))
        v['items'][0]['evidence'][0]['text']='fabricated'
        with self.assertRaises(InputError):la.make_request(v['run'],v['unit'],v['items'])

    def test_all_items_share_one_prefix_without_splitting_the_contribution(self):
        v=control(CASES[0]);items=deepcopy(v['items']);items.append({**deepcopy(items[0]),'id':'w2','work':'A separate local work object'})
        before=deepcopy(v['unit']);r=la.make_request(v['run'],v['unit'],items)
        self.assertEqual(set(r['questions']),{'w1','w2'});self.assertEqual(v['unit'],before)
        self.assertEqual(r['state']['activity'],'orient')

    def test_saved_argmax_reused_after_appending_unrelated_future(self):
        v=control(CASES[0]);calls=[]
        def transport(r):
            calls.append(r)
            return {'model':r['model'],'answers':{k:{'type':'choice','choice':'ordinary_work','confidence':0,
                'probabilities':{x:float(x=='prospective_adjustment') for x in q['criteria']}} for k,q in r['questions'].items()}}
        with TemporaryDirectory() as folder:
            p=Pipeline(folder,None,transport);r=la.make_request(v['run'],v['unit'],v['items']);first=p.decide(r)
            event(v['run']['events'],kind='message',actor='agent',trajectory_id=v['unit']['trajectory_id'],pointer='/later',text='Later unrelated work')
            second=p.decide(la.make_request(v['run'],v['unit'],v['items']))
            self.assertEqual(first,second);self.assertEqual(len(calls),1);self.assertEqual(first[0]['w1']['value'],'prospective_adjustment')
