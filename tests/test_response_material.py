"""Response material identity, visibility and replay, not semantic accuracy."""
from copy import deepcopy
import tempfile
import unittest

from tracker.schema import InputError,digest,dumps
from tracker.feedback_assessments import linked_feedback
from tracker import check_followthrough,response_material
from tests.test_check_followthrough import fixture
from tests.test_check_candidate_repairs import choose


class ResponseMaterialTests(unittest.TestCase):
    def prepared(self,directory):
        run,local,stated,engine=fixture(directory)
        engine.transport=lambda req:choose(req,'none' if req['state']['stage']=='later_check_dispatch' else 'absent')
        later=check_followthrough.build(run,local,stated,engine.decide)
        return run,local,stated,later,engine

    def test_delivery_sees_only_bound_operation_response_and_omissions(self):
        with tempfile.TemporaryDirectory() as directory:
            run,local,stated,later,engine=self.prepared(directory)
            response=linked_feedback(run,local)[1]
            response['event']['text']='head '+('x'*5000)+'HIDDEN_MIDDLE'+('y'*5000)+' data:image/png;base64,QUJDRA== tail'
            req=response_material.delivery_request(run,local,response)
            body=dumps(req)
            self.assertNotIn('FIRST_RESPONSE_ONLY',body);self.assertNotIn('FUTURE_CLAIM',body)
            self.assertNotIn('HIDDEN_MIDDLE',body);self.assertNotIn('QUJDRA==',body)
            self.assertEqual([p['id'] for p in req['state']['prefix']],
                [response['action']['source']['event_id'],response['event']['id']])
            self.assertTrue(req['state']['inspected_response']['unobserved_inline_media'])
            self.assertEqual(req['state']['cutoff_event_id'],response['event']['id'])
            with self.assertRaisesRegex(InputError,'exactly match'):
                forged=deepcopy(response);forged['event']['text']='a fabricated result'
                response_material.delivery_request(run,local,forged)

    def test_form_preserves_entity_scope_and_never_receives_previous_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            run,local,stated,later,engine=self.prepared(directory)
            pair=response_material.pairs(run,local,stated,later)[1]
            req=response_material.form_request(run,local,*(pair[k] for k in ('owner','check','facet','action','response')))
            self.assertEqual(req['state']['inspected_response']['text'],'SECOND_RESPONSE_ONLY: no such card')
            self.assertNotIn('FIRST_RESPONSE_ONLY',dumps(req));self.assertNotIn('FUTURE_CLAIM',dumps(req))
            self.assertNotIn('previous_choice',dumps(req));self.assertNotIn('dispatch_choice',dumps(req))
            self.assertIn('CARD_B',dumps(req));self.assertIn('card balance',dumps(req))
            self.assertEqual(set(req['questions']['choice']['criteria']),set(response_material.FORMS))
            wrong=deepcopy(pair['response']);wrong['action']=local['units'][1]
            with self.assertRaisesRegex(InputError,'exactly match'):
                response_material.form_request(run,local,pair['owner'],pair['check'],pair['facet'],pair['action'],wrong)

    def test_dispatch_delivery_uses_local_contents_without_output_or_later_terms(self):
        with tempfile.TemporaryDirectory() as directory:
            run,local,stated,later,engine=self.prepared(directory)
            response=linked_feedback(run,local)[0]
            req=response_material.delivery_request(run,local,response,response_material.DISPATCH_VERSION)
            self.assertEqual(req['state']['cutoff_event_id'],response['action']['source']['event_id'])
            self.assertEqual(len(req['state']['prefix']),1)
            self.assertIn('local_operation',req['state'])
            self.assertNotIn('FIRST_RESPONSE_ONLY',dumps(req));self.assertNotIn('SECOND_RESPONSE_ONLY',dumps(req))
            self.assertNotIn('NEW_TERMS',dumps(req));self.assertNotIn('FUTURE_CLAIM',dumps(req))
            engine.transport=lambda req:choose(req,'read' if req['state']['stage']=='response_delivery' else 'absent')
            original=response_material.build(run,local,stated,later,engine.decide)
            calls=engine.calls
            revised=response_material.build(run,local,stated,later,engine.decide,response_material.DISPATCH_VERSION)
            self.assertEqual(engine.calls-calls,2)
            self.assertEqual(original['observations'],revised['observations'])
            for result in [original,revised]:
                self.assertTrue(response_material.audit(run,local,stated,later,result,directory)['argmax_replayed'])

    def test_new_projection_replaces_only_matching_material_edges_without_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            run,local,stated,later,engine=self.prepared(directory)
            originals=deepcopy((stated,later))
            engine.transport=lambda req:choose(req,'change' if req['state']['stage']=='response_delivery' else 'reference_only')
            result=response_material.build(run,local,stated,later,engine.decide)
            self.assertEqual((stated,later),originals)
            self.assertEqual(len(result['deliveries']),2);self.assertEqual(len(result['observations']),2)
            first=result['relations'][0]
            old={**first,'type':'provides_check_material','harness':check_followthrough.VERSION}
            unrelated={**old,'facet_id':'another-facet'}
            dispatch={**old,'from':first['action_unit_id'],'type':'attempts_stated_check'}
            relations=[old,unrelated,dispatch];before=deepcopy(relations)
            projected=response_material.project_relations(relations,result)
            self.assertEqual(relations,before);self.assertNotIn(old,projected)
            self.assertIn(unrelated,projected);self.assertIn(dispatch,projected)
            self.assertEqual(len(projected),4)
            self.assertTrue(all(r['previous_choice']=='absent' for r in result['observations']))
            self.assertTrue(all(r['choice']=='reference_only' for r in result['observations']))
            calls=engine.calls
            self.assertEqual(response_material.build(run,local,stated,later,engine.decide),result)
            self.assertEqual(engine.calls,calls)
            self.assertTrue(response_material.audit(run,local,stated,later,result,directory)['argmax_replayed'])
            result['observations'][0]['choice']='contents'
            with self.assertRaisesRegex(InputError,'dependency replay'):
                response_material.audit(run,local,stated,later,result,directory)

    def test_uninspected_selection_is_flagged_not_overridden(self):
        with tempfile.TemporaryDirectory() as directory:
            run,local,stated,later,engine=self.prepared(directory)
            engine.transport=lambda req:choose(req,'read' if req['state']['stage']=='response_delivery' else 'recorded_uninspected')
            result=response_material.build(run,local,stated,later,engine.decide)
            self.assertTrue(all(r['choice']=='recorded_uninspected' and r['review_flags'] for r in result['observations']))
            self.assertEqual({r['type'] for r in result['relations']},{'has_uninspected_material'})

    def test_dependency_and_pair_identity_errors_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            run,local,stated,later,engine=self.prepared(directory)
            changed=deepcopy(later);changed['stated_checks_hash']='wrong'
            with self.assertRaisesRegex(InputError,'dependency changed'):response_material.pairs(run,local,stated,changed)
            changed=deepcopy(later);changed['observations'][0]['actions'].append(deepcopy(changed['observations'][0]['actions'][0]))
            with self.assertRaisesRegex(InputError,'Duplicate'):response_material.pairs(run,local,stated,changed)
            changed=deepcopy(later);changed['observations'][0]['actions'][0]['facets'][0]['responses'][0]['event_id']='wrong'
            with self.assertRaisesRegex(InputError,'binding'):response_material.pairs(run,local,stated,changed)


if __name__=='__main__': unittest.main()
