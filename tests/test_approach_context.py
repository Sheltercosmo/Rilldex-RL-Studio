"""Preserve selected reasons and separately attributed response evidence."""
from copy import deepcopy
from unittest import TestCase
from tracker import adaptation_patterns as ap
from tests.test_work_episodes import example,edge,unit_at
from tests.test_adaptation_patterns import comparison


def fixture():
    run,graph,actions=example(('A','A','Z'))
    edge(graph,actions[1],actions[0],'same_action_target')
    event=next(e for e in run['events'] if e['index']==next(e['index'] for e in run['events'] if e['id']==actions[1]['source']['event_id'])-1)
    reason=unit_at(graph,event['id']);reason['kind']='semantic'
    m=comparison(graph,actions[1],actions[0],'reconfigured_procedure',stated_basis=reason['id'],
        rationale_candidate_ids=[reason['id']],inspector_context={'source_ranges':[reason['source']]})
    return run,graph,actions,reason,m


class ApproachContextTests(TestCase):
    def test_exact_selected_expression_and_native_feedback_are_both_available(self):
        _,g,a,reason,_=fixture();before=deepcopy(g)
        result=ap.project(g);r=result['records'][0]
        self.assertEqual(r['stated_reason']['node_id'],reason['id'])
        self.assertEqual(r['stated_reason']['text'],reason['source']['text'])
        self.assertEqual(r['stated_reason']['attribution'],'agent_expression')
        self.assertEqual(r['response_context']['previous']['status'],'available')
        self.assertEqual(r['response_context']['current']['status'],'available')
        self.assertEqual([r['text'] for r in r['response_context']['current']['records']],['Returned A'])
        self.assertEqual(g,before)
        self.assertEqual(result['procedure_change']['value'],1)
        self.assertNotIn('success',r)

    def test_reason_requires_the_selected_candidate_and_visible_exact_source(self):
        for corrupt in ('not_candidate','not_supplied','different_actor','different_context','copied','misquoted','ungrounded'):
            _,g,a,reason,m=fixture();node=next(n for n in g['nodes'] if n['id']=='event:'+reason['source']['event_id'])
            if corrupt=='not_candidate':m['rationale_candidate_ids']=[]
            elif corrupt=='not_supplied':m['inspector_context']['source_ranges']=[]
            elif corrupt=='different_actor':node['properties']['actor']='user';reason['actor']='user'
            elif corrupt=='different_context':node['properties']['context_id']='other-session'
            elif corrupt=='copied':node['properties']['copied_context']=True
            elif corrupt=='misquoted':reason['source']['text']='invented reason'
            elif corrupt=='ungrounded':g['edges']=[e for e in g['edges'] if not(e['source']==reason['id'] and e['type']=='grounded_in')]
            self.assertEqual(ap.project(g)['records'][0]['stated_reason']['status'],'unavailable',corrupt)

    def test_later_reason_cannot_explain_an_earlier_dispatch(self):
        run,g,a,_,m=fixture();later=next(e for e in run['events'] if e['index']==next(e['index'] for e in run['events'] if e['id']==a[2]['source']['event_id'])-1)
        reason=unit_at(g,later['id']);reason['kind']='semantic'
        m.update(stated_basis=reason['id'],rationale_candidate_ids=[reason['id']],inspector_context={'source_ranges':[reason['source']]})
        r=ap.project(g)['records'][0]
        self.assertEqual(r['stated_reason']['status'],'unavailable')
        self.assertEqual(r['procedure'],'unresolved')

    def test_explicit_reason_choices_stay_distinct_from_missing_inspection(self):
        for choice in ('no_expressed_basis','distributed_basis','unresolved_basis','not_inspected'):
            _,g,_,_,m=fixture();m['stated_basis']=choice
            r=ap.project(g)['records'][0]['stated_reason']
            self.assertEqual(r['status'],choice);self.assertIsNone(r['text']);self.assertIsNone(r['node_id'])

    def test_missing_or_late_feedback_does_not_become_a_later_success(self):
        for mode in ('missing','late','shared'):
            _,g,a,_,_=fixture()
            previous_event='event:'+a[0]['source']['event_id'];current_event='event:'+a[1]['source']['event_id']
            if mode=='missing':g['edges']=[e for e in g['edges'] if not(e['type']=='response_to' and e['target']==current_event)]
            else:
                first=next(e for e in g['edges'] if e['type']=='response_to' and e['target']==previous_event)
                if mode=='late':next(n for n in g['nodes'] if n['id']==first['source'])['event_index']=999
                else:edge(g,first['source'],current_event,'response_to')
            r=ap.project(g)['records'][0]
            side='current' if mode=='missing' else 'previous'
            self.assertEqual(r['response_context'][side]['status'],'unavailable',mode)
            self.assertTrue(r['response_context'][side]['reasons'])

    def test_duplicate_method_choices_never_pick_an_arbitrary_reason(self):
        _,g,_,_,m=fixture();g['semantic_context']['work_observations']['method_observations'].append(deepcopy(m))
        r=ap.project(g)['records'][0]
        self.assertEqual(r['stated_reason']['status'],'unavailable')
        self.assertEqual(r['procedure'],'unresolved')
