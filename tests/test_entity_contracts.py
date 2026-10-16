import unittest
from tracker.entity_contracts import CONTRACTS, FIELD_RULES, route


class EntityContractTests(unittest.TestCase):
    def test_every_field_has_a_role_specific_contract(self):
        self.assertEqual({a+'__'+role for a,fs in CONTRACTS.items() for role,_,_ in fs},set(FIELD_RULES))
    def unit(self, **kwargs):
        return {'eligible':True,'annotation_status':'decided','activities':['coordinate'],
                'expression':{'value':'requested'},**kwargs}

    def test_request_routes_to_recipient_and_requested_operation_not_execution(self):
        r=route(self.unit())
        self.assertEqual(r['next_stage'],'category_entity_extraction')
        self.assertEqual({f['role'] for f in r['routes'][0]['fields']},{'requested_operation','addressee_mention','request_target'})
        self.assertTrue(all(f['status']=='not_extracted' for f in r['routes'][0]['fields']))

    def test_multiple_activities_keep_their_own_fields_without_creating_entities(self):
        r=route(self.unit(activities=['reason','hypothesize']))
        self.assertEqual([x['activity'] for x in r['routes']],['reason','hypothesize'])
        self.assertEqual(r['extraction_status'],'not_started')
        self.assertNotIn('entities',r)

    def test_missing_base_and_social_expression_have_different_next_steps(self):
        self.assertEqual(route(self.unit(annotation_status='unobserved'))['next_stage'],'base_annotation')
        self.assertEqual(route(self.unit(activities=[],expression={'value':'non_propositional'}))['next_stage'],'no_extraction_needed')
        self.assertEqual(route(self.unit(activities=[],expression={'value':'unresolved'}))['next_stage'],'base_annotation_review')

    def test_broad_plan_does_not_create_organization_or_scope(self):
        fields=route(self.unit(activities=['plan']))['routes'][0]['fields']
        self.assertEqual([f['role'] for f in fields],['intended_operation','intended_target','expressed_subgoal'])
        self.assertNotIn('organization_scope',{f['role'] for f in fields})


if __name__=='__main__':unittest.main()
