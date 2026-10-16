import unittest

from tracker.entity_candidates import span_candidates, field_candidates, recorded_action


def source(text, dispatch=False):
    unit={'id':'u1','event_id':'e1','kind':'action_dispatch' if dispatch else 'model_span',
          'text':text,'start':0,'end':len(text),'source_pointer':'/source/0'}
    event={'id':'e1','text':text,'source_pointer':'/source/0','tool':'shell','arguments':{'command':text}}
    return unit,event


class EntityCandidateTests(unittest.TestCase):
    def test_edit_body_keeps_indentation_and_is_not_offered_as_operation_or_target(self):
        u,e=source('edit 8:12\n    return value if condition else None\nend_of_edit',True)
        cs,_=span_candidates(u,e)
        self.assertEqual([c['text'] for c in field_candidates('operation',cs,u)],['edit 8:12'])
        self.assertEqual([c['text'] for c in field_candidates('content',cs,u)],['    return value if condition else None'])
        self.assertEqual(field_candidates('mention',cs,u),[])
        for c in cs:
            if c['kind']=='source_span':self.assertEqual(e['text'][c['start']:c['end']],c['text'])

    def test_recorded_dispatch_does_not_depend_on_semantic_verification_choice(self):
        u,e=source('python reproduce.py',True)
        facts=recorded_action(u,e)
        self.assertEqual(facts['status'],'recorded_dispatch')
        self.assertEqual(facts['operation']['text'],'python reproduce.py')
        self.assertNotIn('success',facts)
        cs,_=span_candidates(u,e)
        self.assertEqual([c['text'] for c in field_candidates('mention',cs,u)],['reproduce.py'])

    def test_conditional_clause_does_not_become_standalone_proposition_candidate(self):
        u,e=source("This will help us determine if there's an issue with the SIM card itself.")
        cs,_=span_candidates(u,e)
        props=field_candidates('proposition',cs,u)
        self.assertEqual([c['text'] for c in props],[u['text'][:-1]])

    def test_purpose_and_operation_have_separate_candidates(self):
        u,e=source('We need to add it to the class to replicate the issue.')
        cs,_=span_candidates(u,e)
        self.assertIn('to replicate the issue',[c['text'] for c in field_candidates('purpose',cs,u)])
        self.assertIn('add it to the class',[c['text'] for c in field_candidates('operation',cs,u)])

    def test_named_tool_arguments_remain_source_values_not_inferred_actors(self):
        u,e=source('lookup({"name": "李🧭"})',True);e['tool']='lookup';e['arguments']={'name':'李🧭'}
        cs,_=span_candidates(u,e);refs=field_candidates('mention',cs,u)
        self.assertEqual(refs[0]['value'],'李🧭');self.assertEqual(refs[0]['normalized_event_pointer'],'/arguments/name')
        self.assertNotIn('actor',refs[0])

    def test_empty_dispatch_and_non_dispatch_do_not_invent_operation(self):
        u,e=source('',True);self.assertIsNone(recorded_action(u,e)['operation'])
        u,e=source('I might try something.');self.assertIsNone(recorded_action(u,e))

    def test_causal_premise_conclusion_boundaries_preserve_negation(self):
        for text,premise,conclusion in [
            ('The output is `True`, which means the issue is not reproduced.','The output is `True`','the issue is not reproduced'),
            ('Since the signal is absent, we should check the cable.','Since the signal is absent','we should check the cable')]:
            u,e=source(text);cs,_=span_candidates(u,e)
            self.assertIn(premise,[c['text'] for c in field_candidates('premise',cs,u)])
            self.assertIn(conclusion,[c['text'] for c in field_candidates('conclusion',cs,u)])

    def test_connective_inside_quoted_text_is_not_an_inference_boundary(self):
        u,e=source('The label is "small therefore fast".')
        cs,_=span_candidates(u,e)
        self.assertFalse(any('premise_clause' in c['proposal_kinds'] for c in cs))


if __name__=='__main__':unittest.main()
