from copy import deepcopy
import unittest
from tracker.actor_intent import packet,DEFINITIONS,HARNESS
from tracker.prefix_encoding import compact,expand
from tracker.relation_contracts import local_plan_packet
from tracker.jev import validate_answers
from tracker.schema import InputError
from test_relation_contracts import evidence


class ActorIntentTests(unittest.TestCase):
    def base(self):
        prefix,source,_=evidence()
        return local_plan_packet(prefix,source)

    def test_only_semantic_contract_changes_source_attribution_and_cutoff_are_preserved(self):
        base=self.base();before=deepcopy(base);request=packet(base);expanded=expand(request)
        self.assertEqual(base,before)
        for field in ('source','prefix','cutoff_event_id','cutoff_codepoint','missingness'):
            self.assertEqual(expanded['state'][field],base['state'][field])
        self.assertEqual(expanded['state']['harness'],HARNESS)
        self.assertEqual(set(request['questions']),set(DEFINITIONS))
        self.assertNotIn('source_plan',request['questions'])
        self.assertEqual(request,packet(compact(base)))

    def test_multiple_properties_can_win_without_confidence_filter_or_cross_field_repair(self):
        request=packet(self.base())
        response={'answers':{k:{'type':'choice','choice':'absent','confidence':0,
                   'probabilities':{'present':.34,'absent':.33,'unresolved':.33}} for k in DEFINITIONS}}
        answers=validate_answers(response,request)
        self.assertTrue(all(a['value']=='present' and a['status']=='decided' for a in answers.values()))
        response['answers']['own_intended_work']['probabilities']={'present':.2,'absent':.3,'unresolved':.5}
        answers=validate_answers(response,request)
        self.assertEqual(answers['own_intended_work']['value'],'unresolved')
        self.assertEqual(answers['other_request']['value'],'present')

    def test_unregistered_source_questions_or_future_state_are_rejected(self):
        for field in ('questions','model'):
            changed=self.base();changed[field]={} if field=='questions' else 'different'
            with self.assertRaises(InputError):packet(changed)
        changed=self.base();changed['state']['prior_plan_result']='present'
        with self.assertRaises(InputError):packet(changed)


if __name__=='__main__':unittest.main()
