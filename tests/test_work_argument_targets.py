"""Argument role and predicate selection, including retained source identity."""
from copy import deepcopy
import unittest
from tracker import work_content_bindings as contents, work_content_targets as targets
from tracker import work_qualified_contents as qualified
from tracker.schema import InputError
from test_work_content_targets import case, proposed
from test_work_qualified_contents import choose, inventory, scope


def argument_case(text='The compiler is unavailable.',owner='The compiler is unavailable',argument='The compiler'):
    p,b=case(text,owner,argument)
    raw=deepcopy(b['raw_response']);raw['features'][0].update(type='target',id='argument')
    return p,contents.bind(p,contents.request(p,b['unit_id']),raw,'argument structural control')


class ArgumentTargetTests(unittest.TestCase):
    def test_joint_role_and_predicate_replaces_proposer_type_without_source_changes(self):
        p,b=argument_case();t=proposed(p,b);before=deepcopy((p,b,t))
        req=targets.request(p,b,'argument',t,version=targets.ARGUMENT_SELECTOR_VERSION)
        raw=choose(req,{'target':'state_bearer::whole_content','form':'literal'})
        d=targets.resolve(p,b,'argument',t,raw,version=targets.ARGUMENT_SELECTOR_VERSION)
        v=targets.project(p,b,'argument',t,d)
        self.assertEqual(v['qualification']['role'],'state_bearer')
        self.assertEqual(v['qualification']['feature']['type'],'argument')
        self.assertEqual(v['qualification']['feature']['proposed_type'],'target')
        self.assertEqual(v['qualification']['target']['expression'],b['contents'][0]['expression'])
        self.assertEqual(v['new_work_items'],[])
        self.assertEqual((p,b,t),before)

    def test_nested_actor_uses_embedded_predicate_and_keeps_reference_form(self):
        p,b=argument_case('Confirm if you want me to list them.','Confirm if you want me to list them','me')
        t=proposed(p,b,'me to list them','me','them');part=next(x for x in t['parts'] if x['expression']['text']=='me to list them')
        req=targets.request(p,b,'argument',t,version=targets.ARGUMENT_SELECTOR_VERSION)
        raw=choose(req,{'target':'actor::'+part['id'],'form':'unresolved_reference'})
        # Deliberately tiny winning margin and contradictory convenience fields.
        probs=raw['answers']['target']['probabilities'];total=len(probs)+.01
        raw['answers']['target'].update(choice='outside_content',confidence=0,
            probabilities={k:(1.01 if v else 1)/total for k,v in probs.items()})
        d=targets.resolve(p,b,'argument',t,raw,version=targets.ARGUMENT_SELECTOR_VERSION)
        v=targets.project(p,b,'argument',t,d)
        self.assertEqual(v['qualification']['target']['expression']['text'],'me to list them')
        self.assertEqual(v['qualification']['role'],'actor')
        self.assertEqual(v['qualification']['feature']['form'],'unresolved_reference')
        self.assertEqual(v['qualification']['execution_status'],'not_established_by_prose')

    def test_missing_outside_and_unknown_form_do_not_invent_role(self):
        p,b=argument_case();t=proposed(p,b)
        req=targets.request(p,b,'argument',t,version=targets.ARGUMENT_SELECTOR_VERSION)
        for choice in ['outside_content','missing_detail','unresolved']:
            d=targets.resolve(p,b,'argument',t,choose(req,{'target':choice}),version=targets.ARGUMENT_SELECTOR_VERSION)
            self.assertIsNone(d['role']);self.assertIsNone(targets.project(p,b,'argument',t,d)['qualification'])
        d=targets.resolve(p,b,'argument',t,choose(req,{'target':'actor::whole_content','form':'unresolved'}),version=targets.ARGUMENT_SELECTOR_VERSION)
        self.assertEqual(d['status'],'unresolved_form')
        self.assertIsNone(targets.project(p,b,'argument',t,d)['qualification'])

    def test_qualified_relationship_input_retains_selected_role(self):
        p,b=argument_case();t=proposed(p,b)
        req=targets.request(p,b,'argument',t,version=targets.ARGUMENT_SELECTOR_VERSION)
        d=targets.resolve(p,b,'argument',t,choose(req,{'target':'state_bearer::whole_content'}),version=targets.ARGUMENT_SELECTOR_VERSION)
        reviews=dict(inventory_selection=inventory(p,b),scope_reviews=[dict(decision=scope(p,b,'argument',['switch']))],
            target_reviews=[dict(targets=t,decision=d)])
        view=qualified.project(p,b,**reviews)
        self.assertTrue(view['ready_for_relationships'])
        row=view['qualifications'][0]
        self.assertEqual(row['feature']['type'],'argument')
        self.assertEqual(row['targets'][0]['role'],'state_bearer')
        req=qualified.relationship_request(p,b,**reviews)
        self.assertEqual(req['argument_role_questions'],targets.ARGUMENT_ROLES)
        links=qualified.bind_links(p,b,dict(links=[],content_issues=[]),'structural control',**reviews)
        selection=qualified.selection_request(p,b,links,**reviews)
        self.assertEqual(selection['state']['qualifications'],view['qualifications'])
        observed=qualified.observation(p,b,links,choose(selection),**reviews)
        self.assertEqual(observed['argument_role_questions'],targets.ARGUMENT_ROLES)

    def test_mixed_legacy_and_argument_targets_are_not_fully_role_reviewed(self):
        p,b=argument_case('The compiler is unavailable; the linker is ready.',
                         'The compiler is unavailable','The compiler')
        raw=deepcopy(b['raw_response'])
        raw['contents'].append(dict(id='linker',kind='state',mode='asserted',expression={'text':'the linker is ready'}))
        raw['features'][0]['scopes']=[['switch','linker']]
        b=contents.bind(p,contents.request(p,b['unit_id']),raw,'mixed review structural control')
        reviews=[]
        for cid,version in [('switch',targets.ARGUMENT_HEAD_VERSION),('linker',targets.VERSION)]:
            t=targets.bind(p,b,cid,[],producer='structural control')
            req=targets.request(p,b,'argument',t,version=version)
            choice='state_bearer::whole_content' if cid=='switch' else 'whole_content'
            d=targets.resolve(p,b,'argument',t,choose(req,{'target':choice}),version=version)
            reviews.append(dict(targets=t,decision=d))
        v=qualified.project(p,b,inventory_selection=inventory(p,b),
            scope_reviews=[dict(decision=scope(p,b,'argument',['switch','linker']))],target_reviews=reviews)
        self.assertFalse(v['ready_for_relationships'])
        self.assertEqual([i['type'] for i in v['issues']],['argument_role_not_reviewed'])

    def test_old_selector_unchanged_and_nonargument_feature_rejected(self):
        p,b=argument_case();t=proposed(p,b)
        req=targets.request(p,b,'argument',t)
        self.assertEqual(req['state']['harness'],targets.VERSION)
        self.assertEqual(set(req['questions']),{'target'})
        p,b=case();t=proposed(p,b)
        with self.assertRaises(InputError):targets.request(p,b,'condition',t,version=targets.ARGUMENT_SELECTOR_VERSION)


if __name__=='__main__':unittest.main()
