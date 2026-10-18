from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tracker import work_content_bindings as contents, work_content_targets as details
from tracker import work_scope_interpretations as scopes, work_qualified_contents as qualified
from tracker.schema import InputError, digest


FIXTURES=Path(__file__).parent/'fixtures/feature-membership'


def saved(filename,name):
    return next(c for c in json.loads((FIXTURES/filename).read_text(encoding='utf-8'))['cases'] if c['case']==name)


def choose(req, choices=None):
    choices=choices or {}
    return dict(model=req['model'],answers={k:dict(type='choice',probabilities={
        option:float(option==choices.get(k,next(iter(q['criteria'])))) for option in q['criteria']})
        for k,q in req['questions'].items()})


def inventory(p,b,choice='adequate'):
    # Software-contract control. This manufactured assessment does not certify
    # the deliberately partial inventories in these development fixtures.
    req=contents.selection_request(p,b)
    return contents.select(p,b,choose(req,{'inventory':choice}))


def scope(p,b,fid,ids,application='individual',sentinel=None):
    req=scopes.request(p,b,fid)
    choice=sentinel or next(r['id'] for r in req['state']['readings']
        if r['content_ids']==sorted(ids) and r['application']==application)
    return scopes.resolve(p,b,fid,choose(req,{'reading':choice}))


def retail(name='retail-detail'):
    c=saved('content-detail-targets.json',name); p,b=c['packet'],c['bound']
    reviews=dict(inventory_selection=inventory(p,b),
        scope_reviews=[dict(decision=scope(p,b,c['feature_id'],[c['content_id']]))],
        target_reviews=[dict(targets=c['targets'],decision=c['result'])])
    return p,b,reviews,c


def group(name='joint-negation'):
    c=saved('scope-interpretations.json',name); p,b=c['packet'],c['bound']
    return p,b,dict(inventory_selection=inventory(p,b),scope_reviews=[dict(decision=c['result'])])


class QualifiedContentTests(unittest.TestCase):
    def test_recorded_joint_selection_reaches_link_stage_without_distribution(self):
        p,b,r=group(); before=deepcopy((p,b,r))
        view=qualified.project(p,b,**r)
        self.assertTrue(view['ready_for_relationships'])
        self.assertEqual(view['contents'],b['contents'])
        row=view['qualifications'][0]
        self.assertEqual(row['feature']['expression']['text'],'Do not both')
        self.assertEqual(row['application'],'joint')
        self.assertEqual(row['targets'][0]['content_ids'],['delete','overwrite'])
        self.assertEqual(row['targets'][0]['distribution'],'not_distributed')
        req=qualified.relationship_request(p,b,**r)
        self.assertEqual(req['qualifications'],view['qualifications'])
        self.assertTrue(all('features' not in c for c in req['contents']))
        self.assertEqual((p,b,r),before)

    def test_recorded_detail_does_not_qualify_whole_action_or_add_work(self):
        p,b,r,c=retail(); view=qualified.project(p,b,**r)
        self.assertTrue(view['ready_for_relationships'])
        q=view['qualifications'][0]['targets'][0]
        self.assertEqual(q['target']['kind'],'content_detail')
        self.assertEqual(q['target']['expression']['text'],'preferably white if available')
        self.assertEqual(q['content_id'],'c4')
        req=qualified.relationship_request(p,b,**r)
        self.assertEqual(req['contents'],b['contents'])
        self.assertEqual(req['review_hash'],digest(view))
        self.assertEqual(len(req['contents']),len(b['contents']))
        self.assertEqual(view['execution_status'],'not_established_by_prose')
        self.assertEqual(view['publication'],'review_only')

    def test_review_completeness_does_not_relabel_retained_semantic_failure(self):
        # Recorded Jev selected joint for "neither ... nor". Preserve the failure
        # for review instead of claiming that a complete receipt fixes meaning.
        p,b,r=group('neither-coordination')
        view=qualified.project(p,b,**r)
        self.assertTrue(view['ready_for_relationships'])
        self.assertEqual(view['qualifications'][0]['application'],'joint')
        self.assertIn('not independent semantic accuracy',view['limit'])

    def test_missing_inventory_scope_or_target_blocks_relationship_construction(self):
        p,b,r,c=retail()
        for missing in ['inventory_selection','scope_reviews','target_reviews']:
            args=deepcopy(r); args.pop(missing)
            with self.subTest(missing=missing):
                view=qualified.project(p,b,**args)
                self.assertFalse(view['ready_for_relationships'])
                self.assertEqual(len(view['qualifications']),len(b['features']))
                with self.assertRaisesRegex(InputError,'reviews incomplete or disagree'):
                    qualified.relationship_request(p,b,**args)

    def test_missing_detail_and_outside_owner_results_remain_blocking(self):
        for name in ['retail-missing-detail','outside-owner']:
            p,b,r,c=retail(name); view=qualified.project(p,b,**r)
            with self.subTest(case=name):
                self.assertFalse(view['ready_for_relationships'])
                self.assertIn('target_'+c['result']['status'],[issue['type'] for issue in view['issues']])
                self.assertIsNone(view['qualifications'][0]['targets'][0]['target'])

    def test_unresolved_scope_keeps_conflicting_target_review_visible(self):
        p,b,r,c=retail()
        for sentinel in ['unresolved','no_suitable_reading']:
            r['scope_reviews']=[dict(decision=scope(p,b,c['feature_id'],[],sentinel=sentinel))]
            view=qualified.project(p,b,**r)
            self.assertFalse(view['ready_for_relationships'])
            self.assertIn('scope_'+sentinel,[issue['type'] for issue in view['issues']])
            self.assertIn('target_scope_disagreement',[issue['type'] for issue in view['issues']])

    def test_target_for_different_owner_or_joint_group_cannot_override_scope(self):
        p,b,r,c=retail()
        r['scope_reviews']=[dict(decision=scope(p,b,c['feature_id'],['c1']))]
        view=qualified.project(p,b,**r)
        self.assertEqual({i['type'] for i in view['issues']},{'target_not_reviewed','target_scope_disagreement'})
        p,b,r=group(); fid=b['features'][0]['id']
        t=details.bind(p,b,'delete',[],producer='conflicting target control')
        req=details.request(p,b,fid,t)
        r['target_reviews']=[dict(targets=t,decision=details.resolve(p,b,fid,t,choose(req)))]
        view=qualified.project(p,b,**r)
        self.assertFalse(view['ready_for_relationships'])
        self.assertEqual(view['qualifications'][0]['application'],'joint')
        self.assertEqual(view['issues'][0]['type'],'target_scope_disagreement')

    def test_each_individually_selected_member_needs_its_own_target_review(self):
        p,b,r=group('shared-negation'); fid=b['features'][0]['id']
        # Recorded shared-negation selected individual attachment to two items.
        self.assertEqual(r['scope_reviews'][0]['decision']['selected']['application'],'individual')
        r['target_reviews']=[]
        for cid in ['delete','overwrite']:
            t=details.bind(p,b,cid,[],producer='whole member structural control')
            req=details.request(p,b,fid,t)
            r['target_reviews'].append(dict(targets=t,decision=details.resolve(p,b,fid,t,choose(req))))
            view=qualified.project(p,b,**r)
            self.assertEqual(view['ready_for_relationships'],cid=='overwrite')
        self.assertEqual([t['target']['kind'] for t in view['qualifications'][0]['targets']],['whole_content']*2)

    def test_nonadequate_inventory_cannot_be_bypassed_by_resolved_attachments(self):
        p,b,r,c=retail()
        for value in ['incorrect','incomplete','unresolved']:
            r['inventory_selection']=inventory(p,b,value)
            view=qualified.project(p,b,**r)
            self.assertFalse(view['ready_for_relationships'])
            self.assertIn('inventory_'+value,[i['type'] for i in view['issues']])

    def test_older_attachment_choices_are_not_reused_as_scope_reviews(self):
        p,b,r,c=retail(); req=contents.selection_request(p,b)
        r['inventory_selection']=contents.select(p,b,choose(req,{'f0':'unresolved'}))
        self.assertFalse(r['inventory_selection']['ready_for_relationships'])
        self.assertTrue(qualified.project(p,b,**r)['ready_for_relationships'])
        r.pop('scope_reviews')
        self.assertFalse(qualified.project(p,b,**r)['ready_for_relationships'])

    def test_syntax_augmented_scope_requires_its_original_syntax_receipt(self):
        p,b,r=group('shared-negation'); fid=b['features'][0]['id']
        recorded=saved('syntax-context.json','shared-negation')['syntax']
        req=scopes.request(p,b,fid,syntax=recorded)
        key=next(row['id'] for row in req['state']['readings']
            if row['application']=='joint' and row['content_ids']==['delete','overwrite'])
        # This deliberately incorrect reading tests receipt plumbing, not meaning.
        decision=scopes.resolve(p,b,fid,choose(req,{'reading':key}),syntax=recorded)
        r['scope_reviews']=[dict(decision=decision,syntax=recorded)]
        self.assertTrue(qualified.project(p,b,**r)['ready_for_relationships'])
        r['scope_reviews']=[dict(decision=decision)]
        with self.assertRaises(InputError):qualified.project(p,b,**r)

    def test_duplicates_changed_receipts_and_other_inventory_are_rejected(self):
        p,b,r,c=retail()
        for key in ['scope_reviews','target_reviews']:
            changed=deepcopy(r); changed[key]*=2
            with self.subTest(key=key),self.assertRaises(InputError):qualified.project(p,b,**changed)
        changed=deepcopy(r); changed['target_reviews'][0]['decision']['status']='whole_content'
        with self.assertRaises(InputError):qualified.project(p,b,**changed)
        body=deepcopy(b['raw_response']); body['contents'][0]['mode']='hypothetical'
        other=contents.bind(p,contents.request(p,b['unit_id']),body,'changed inventory')
        with self.assertRaises(InputError):qualified.project(p,other,**r)

    def test_link_pipeline_retains_qualification_context_and_raw_argmax(self):
        p,b,r=group(); before=deepcopy((p,b,r))
        proposal=dict(links=[dict(source='list',target='delete',type='before',
            evidence=dict(text=p['units'][0]['source']['text']))],content_issues=[])
        with patch('tracker.jev.JevClient._post',side_effect=AssertionError('no new model calls')):
            links=qualified.bind_links(p,b,proposal,'structural link control',**r)
            req=qualified.selection_request(p,b,links,**r)
            raw=choose(req)
            raw['answers']['l0'].update(choice='unsupported',confidence=0,
                probabilities=dict(supported=.34,unsupported=.33,unresolved=.33))
            result=qualified.observation(p,b,links,raw,**r)
        self.assertEqual(result['supported_links'],['l0'])
        self.assertEqual(result['qualifications'],req['state']['qualifications'])
        self.assertEqual(result['contents'],b['contents'])
        self.assertEqual(result['response'],raw)
        self.assertEqual(result['publication'],'review_only')
        self.assertEqual(result['execution_status'],'not_established_by_prose')
        self.assertEqual((p,b,r),before)

    def test_details_are_not_link_endpoints_and_reported_content_issues_block(self):
        p,b,r,c=retail()
        for response in [dict(links=[dict(source=c['result']['detail']['id'],target='c1',type='before',
                evidence=dict(text='if available'))],content_issues=[]),
            dict(links=[],content_issues=[dict(issue='wrong content')])]:
            with self.assertRaises(InputError):qualified.bind_links(p,b,response,'control',**r)

    def test_changed_links_foreign_model_and_payload_overflow_fail(self):
        p,b,r=group()
        links=qualified.bind_links(p,b,dict(links=[],content_issues=[]),'structural negative control',**r)
        changed=deepcopy(links); changed['request_hash']='wrong'
        with self.assertRaises(InputError):qualified.selection_request(p,b,changed,**r)
        req=qualified.selection_request(p,b,links,**r); raw=choose(req); raw['model']='other'
        with self.assertRaises(InputError):qualified.observation(p,b,links,raw,**r)
        with patch.object(contents,'MAX_SELECTION_BYTES',100),self.assertRaises(InputError):
            qualified.relationship_request(p,b,**r)


if __name__=='__main__':unittest.main()
