from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from tracker import work_content_audit as audit, work_content_stages as stages
from tracker.schema import InputError
import test_work_content_stages as content_tests


def response(request, overrides=None):
    overrides = overrides or {}
    answers = {}
    for key, q in request['questions'].items():
        chosen = overrides.get(key, 'adequate')
        others = len(q['criteria'])-1
        answers[key] = dict(type='choice', choice='unresolved', confidence=0.001,
            probabilities={k:0.36 if k == chosen else 0.64/others for k in q['criteria']})
    return dict(model=request['model'], answers=answers, usage={'input_tokens':0,'output_tokens':0})


class ContentAuditTests(unittest.TestCase):
    def case(self):
        _, packet, _, _, contents, _, _ = content_tests.ContentStagesTests().case()
        return packet, contents, audit.request(packet, contents)

    def test_request_uses_complete_local_source_and_frozen_content_with_no_base_labels(self):
        p,c,r = self.case()
        self.assertEqual(r['state']['source']['source'],p['units'][0]['source'])
        self.assertEqual(r['state']['contents'],c['mentions'])
        self.assertEqual(len(r['questions']),len(c['mentions'])+1)
        self.assertNotIn('activity',r['state']['source'])
        self.assertNotIn('links',r['state'])

    def test_argmax_ignores_provider_choice_and_confidence(self):
        p,c,r = self.case(); raw=response(r); report=audit.result(p,c,raw)
        self.assertTrue(report['ready_for_relationships'])
        self.assertEqual(report['selection_policy'],'argmax/1')
        self.assertEqual(report['reusable_content_ids'],[m['id'] for m in c['mentions']])
        self.assertEqual(report['content_review_ids'],[])

    def test_one_bad_description_preserves_other_contents_but_blocks_link_generation(self):
        p,c,r=self.case(); before=deepcopy(c); raw=response(r,{'m0':'qualification_changed'}); report=audit.result(p,c,raw)
        self.assertFalse(report['ready_for_relationships'])
        self.assertEqual(report['content_review_ids'],[c['mentions'][0]['id']])
        self.assertEqual(len(report['reusable_content_ids']),len(c['mentions'])-1)
        with self.assertRaisesRegex(InputError,'content review required'): audit.checked(p,c,r,raw,report)
        self.assertEqual(c,before)

    def test_missing_content_cannot_be_hidden_by_all_adequate_mentions(self):
        p,c,r=self.case()
        for coverage in ['missing_content','mispartitioned','unresolved']:
            report=audit.result(p,c,response(r,{'coverage':coverage}))
            self.assertFalse(report['ready_for_relationships']);self.assertEqual(report['content_review_ids'],[])
            self.assertEqual(len(report['reusable_content_ids']),len(c['mentions']))

    def test_empty_inventory_still_needs_coverage_assessment(self):
        p,c,_=self.case();req=stages.content_request(p,c['unit_id'])
        c=stages.bind_contents(p,req,{'mentions':[]},'authored empty'); r=audit.request(p,c)
        self.assertEqual(list(r['questions']),['coverage'])
        self.assertFalse(audit.result(p,c,response(r,{'coverage':'missing_content'}))['ready_for_relationships'])
        self.assertTrue(audit.result(p,c,response(r))['ready_for_relationships'])

    def test_malformed_or_extra_answers_and_changed_model_fail(self):
        p,c,r=self.case()
        for mutate in [lambda x:x['answers'].pop('coverage'),lambda x:x['answers'].update(extra=x['answers']['coverage']),lambda x:x.update(model='different'),lambda x:x['answers']['m0'].update(probabilities={'adequate':1}),lambda x:x['answers']['m0']['probabilities'].update(adequate=float('nan'))]:
            raw=response(r);mutate(raw)
            with self.assertRaises(InputError):audit.result(p,c,raw)

    def test_changed_content_source_request_or_report_is_not_a_reusable_assessment(self):
        p,c,r=self.case();raw=response(r);report=audit.result(p,c,raw)
        changed=deepcopy(c);changed['mentions'][0]['label']='new meaning'
        with self.assertRaises(InputError):audit.checked(p,changed,r,raw,report)
        changed=deepcopy(p);changed['units'][0]['source']['text']+=' altered'
        with self.assertRaises(InputError):audit.checked(changed,c,r,raw,report)
        changed=deepcopy(report);changed['ready_for_relationships']=False
        with self.assertRaises(InputError):audit.checked(p,c,r,raw,changed)
        changed=deepcopy(r);changed['state']['scope']='changed'
        with self.assertRaises(InputError):audit.checked(p,c,changed,raw,report)

    def test_file_workflow_blocks_unaudited_and_retains_exact_failed_delivery(self):
        _,p,_,b,c,_,links=content_tests.ContentStagesTests().case()
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); directory=root/'stages'; body=root/'body.json'; result=root/'audit.json'; relation=root/'links.json'
            stages.prepare_files(p,c['unit_id'],directory);body.write_text(json.dumps(b),encoding='utf-8')
            stages.accept_contents(directory,body,'authored content control','fixture/content')
            relation.write_text(json.dumps(links),encoding='utf-8')
            with self.assertRaisesRegex(InputError,'content audit required'):
                stages.accept_relationships(directory,relation,'author','fixture/relations')
            req=json.loads((directory/'content-audit-request.json').read_text(encoding='utf-8'))
            raw=json.dumps(response(req,{'m0':'qualification_changed'}),indent=2);result.write_bytes(raw.encode('utf-8'))
            first=audit.accept_files(directory,result,'authored audit','fixture/audit')
            self.assertFalse(first['ready_for_relationships']);self.assertFalse(first['reused'])
            self.assertTrue(audit.accept_files(directory,result,'authored audit','fixture/audit')['reused'])
            self.assertEqual(json.loads((directory/'content-audit-delivery.json').read_text(encoding='utf-8'))['raw_output'],raw)
            self.assertFalse((directory/'ready-relationship-request.json').exists())
            with self.assertRaisesRegex(InputError,'content review required'):
                stages.accept_relationships(directory,relation,'author','fixture/relations')
            self.assertFalse((directory/'relationship-delivery.json').exists())
            result.write_text(json.dumps(response(req)),encoding='utf-8')
            with self.assertRaisesRegex(InputError,'artifact differs'):
                audit.accept_files(directory,result,'authored audit','fixture/audit')
            self.assertFalse((directory/'ready-relationship-request.json').exists())

    def test_named_review_resolves_workflow_without_rewriting_argmax(self):
        p,c,r=self.case();raw=response(r,{'m0':'qualification_changed'});before=deepcopy(raw)
        review=audit.review_template(p,c,raw);review['reviewer']={'author':'Authored control reviewer','note':'Checking a model disagreement.'}
        review['mentions'][0].update(decision='include',reason='The proposed mode preserves the intended status in this authored control.')
        resolved=audit.resolve(p,c,raw,review)
        self.assertTrue(resolved['ready_for_relationships']);self.assertEqual(raw,before)
        self.assertEqual(audit.result(p,c,raw)['mentions'][0]['choice'],'qualification_changed')

    def test_named_review_cannot_skip_flagged_items_or_resolve_other_snapshot(self):
        p,c,r=self.case();raw=response(r,{'m0':'wrong_work_content','coverage':'missing_content'})
        good=audit.review_template(p,c,raw);good['reviewer']={'author':'Authored reviewer','note':'Source review.'}
        good['mentions'][0].update(decision='include',reason='Full local source supports this control.')
        good['coverage'].update(decision='include',reason='The complete inventory represents this control.')
        for mutate in [lambda x:x.update(mentions=[]),lambda x:x.update(coverage=None),lambda x:x.update(audit_hash='different'),lambda x:x.update(contents_hash='different'),lambda x:x['reviewer'].update(author=''),lambda x:x['mentions'][0].update(mention_id='foreign'),lambda x:x['mentions'][0].update(reason='')]:
            review=deepcopy(good);mutate(review)
            with self.assertRaises(InputError):audit.resolve(p,c,raw,review)
        self.assertTrue(audit.resolve(p,c,raw,good)['ready_for_relationships'])

    def test_named_reviewer_can_withhold_a_model_accepted_item_and_preserve_others(self):
        p,c,r=self.case();raw=response(r);review=audit.review_template(p,c,raw)
        review['reviewer']={'author':'Authored reviewer','note':'Correcting an accepted observation.'}
        review['mentions']=[dict(mention_id=c['mentions'][0]['id'],decision='withhold',reason='Unsupported interpretation in this control.')]
        resolved=audit.resolve(p,c,raw,review)
        self.assertFalse(resolved['ready_for_relationships']);self.assertEqual(len(resolved['reusable_content_ids']),len(c['mentions'])-1)

    def test_resolved_files_unlock_only_the_unchanged_relationship_request(self):
        _,p,_,b,c,_,links=content_tests.ContentStagesTests().case()
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);directory=root/'stages';external=root/'external.json'
            stages.prepare_files(p,c['unit_id'],directory);external.write_text(json.dumps(b),encoding='utf-8')
            stages.accept_contents(directory,external,'authored content control','fixture/content')
            req=json.loads((directory/'content-audit-request.json').read_text(encoding='utf-8'))
            external.write_text(json.dumps(response(req,{'m0':'wrong_kind_or_mode'})),encoding='utf-8')
            audit.accept_files(directory,external,'authored audit','fixture/audit')
            review=audit.template_files(directory);review['reviewer']={'author':'Authored reviewer','note':'Resolve control mismatch.'}
            review['mentions'][0].update(decision='include',reason='Kind and mode match the source in this control.')
            external.write_text(json.dumps(review),encoding='utf-8')
            self.assertTrue(audit.resolve_files(directory,external)['ready_for_relationships'])
            self.assertTrue(audit.resolve_files(directory,external)['reused'])
            external.write_text(json.dumps(links),encoding='utf-8')
            accepted=stages.accept_relationships(directory,external,'authored relationships','fixture/links')
            self.assertEqual(accepted['links'],1)
            assembled=json.loads((directory/'assembled.json').read_text(encoding='utf-8'))
            self.assertIn('content_audit_hash',assembled)
            ready=directory/'ready-relationship-request.json';original=ready.read_bytes();value=json.loads(original);value['rule']='changed request';ready.write_text(json.dumps(value),encoding='utf-8')
            with self.assertRaisesRegex(InputError,'ready relationship request changed'):
                stages.accept_relationships(directory,external,'authored relationships','fixture/links')
            ready.write_bytes(original)
            reviewed=directory/'resolved-content-audit.json';value=json.loads(reviewed.read_text(encoding='utf-8'));value['review']['reviewer']['note']='changed';reviewed.write_text(json.dumps(value),encoding='utf-8')
            with self.assertRaisesRegex(InputError,'resolved content audit changed'):
                stages.accept_relationships(directory,external,'authored relationships','fixture/links')


if __name__=='__main__':unittest.main()
