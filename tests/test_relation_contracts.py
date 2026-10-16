from copy import deepcopy
import json
import unittest

from tracker.relation_contracts import packet,inconsistencies,source_role_packet,source_plan_packet
from tracker.activity_reference import validate_annotation
from tracker.jev import validate_answers
from tracker.schema import InputError
from research.relation_scope import review_case,rollout_evidence
from test_activity_reference import bundle


def evidence():
    text='I will calculate the total. The total is 42.'
    record={'id':'response','trace_id':'trace','actor_id':'main','event_index':1,
            'source_pointer':'/response','text':text,'role':'model','kind':'text'}
    def endpoint(id,start,end):
        return {'id':id,'trace_id':'trace','actor_id':'main','event_index':1,
                'source_pointer':'/response','start':start,'end':end,'text':text[start:end],'role':'model'}
    return [record],endpoint('plan',0,27),endpoint('total',27,len(text))


class RelationContractTests(unittest.TestCase):
    def test_prefix_and_endpoints_reject_future_cross_actor_and_misbinding(self):
        prefix,a,b=evidence()
        packet(prefix,a,b)
        for changed in ({**a,'actor_id':'other'},{**a,'text':'x'*27},{**a,'start':28,'end':55},b):
            with self.assertRaises(InputError):packet(prefix,changed,b)
        with self.assertRaises(InputError):packet([{**prefix[0],'text':prefix[0]['text']+' future'}],a,b)
        with self.assertRaises(InputError):packet(prefix+[{**prefix[0],'id':'later','event_index':2}],a,b)
        with self.assertRaises(InputError):packet(prefix+prefix,a,b)
        with self.assertRaises(InputError):packet([{**prefix[0],'media':[{'path':'unread.png'}]}],a,b)

    def test_labels_and_rewards_do_not_enter_request_but_recorded_tool_contract_does(self):
        prefix,a,b=evidence();expected=packet(prefix,a,b,native_graph=True)
        for row in prefix:row.update(label='secret',native_edge='secret',reward='secret',confidence=.99)
        self.assertEqual(expected,packet(prefix,a,b,native_graph=True))
        prefix[0]['tool_contract']={'name':'calculator','description':'Compute an expression.'}
        self.assertEqual(packet(prefix,a,b)['state']['prefix'][0]['tool_contract'],prefix[0]['tool_contract'])
        prefix[0]['kind']='action'
        with self.assertRaises(InputError):packet(prefix,a,b,native_graph=True)

    def test_direct_and_broader_questions_have_separate_definitions_and_no_threshold(self):
        request=packet(*evidence(),native_graph=True)
        self.assertEqual(set(request['questions']),{'source_plan','implements_plan','native_reason_execute'})
        self.assertIn('first or later step',request['questions']['implements_plan']['instructions'])
        self.assertIn('first nodes',request['questions']['native_reason_execute']['instructions'])
        self.assertIn('not a distance cutoff',request['questions']['native_reason_execute']['instructions'])
        raw={'answers':{key:{'type':'choice','confidence':0,'choice':'absent',
              'probabilities':{'present':.34,'absent':.33,'unresolved':.33}} for key in request['questions']}}
        self.assertTrue(all(a['value']=='present' for a in validate_answers(raw,request).values()))

    def test_incompatibility_report_never_rewrites_or_uses_confidence(self):
        answers={'source_plan':{'value':'absent','confidence':.99},'implements_plan':{'value':'present','confidence':0},
                 'native_reason_execute':{'value':'present','confidence':0}}
        saved=deepcopy(answers)
        self.assertEqual(inconsistencies(answers),['implementation_without_plan','native_execution_without_plan'])
        self.assertEqual(answers,saved)
        answers['source_plan']['value']='unresolved'
        self.assertEqual(inconsistencies(answers),[])

    def test_source_role_is_invariant_to_later_subjects_and_excludes_future_tail(self):
        prefix,a,b=evidence();one=packet(prefix,a,b,native_graph=True)
        text='A completely different later action.'
        later={**prefix[0],'id':'later','event_index':2,'source_pointer':'/later','text':text}
        c={**b,'id':'later-unit','event_index':2,'source_pointer':'/later','start':0,'end':len(text),'text':text}
        two=packet(prefix+[later],a,c)
        first=source_role_packet(one);second=source_role_packet(two)
        self.assertEqual(first,second)
        self.assertEqual(first['state']['prefix'][0]['text'],a['text'])
        self.assertNotIn('42',json.dumps(first));self.assertNotIn(text,json.dumps(first))
        self.assertNotIn('subject',first['state']);self.assertEqual(first['state']['cutoff_codepoint'],a['end'])
        one['state']['source']['text']='bad'
        with self.assertRaises(InputError):source_role_packet(one)

    def test_plan_observer_supports_final_unit_without_a_fabricated_later_pair(self):
        prefix,a,b=evidence()
        request=source_plan_packet(prefix,b)
        self.assertEqual(request['state']['source'],b)
        self.assertEqual(request['state']['prefix'],prefix)
        self.assertEqual(source_plan_packet(prefix,a),source_role_packet(packet(prefix,a,b)))
        with self.assertRaises(InputError):source_plan_packet(prefix,{**b,'text':'wrong'})
        with self.assertRaises(InputError):source_plan_packet(prefix,{**b,'role':'instruction'})

    def test_blind_pair_review_excludes_native_labels_and_cites_both_spans(self):
        request=packet(*evidence(),native_graph=True)
        case={'case_id':'fixture','trace_id':'trace','domain':'math','adapter':'native-reasoningflow',
              'source_hash':'hash','native_reference':{'value':'secret native label'},'requests':{'scope':request}}
        blind=review_case(case)
        self.assertNotEqual(blind['case_id'],case['case_id'])
        self.assertNotIn('secret native label',json.dumps(blind))
        self.assertNotIn('probabilities',json.dumps(blind))
        row={'annotation_id':'fixture-review','reviewer':'synthetic-test-only','case_hash':blind['case_hash'],'manifest_hash':'manifest',
             'reference_kind':'model_proposal','exposure':'prediction_blind','annotation_type':'independent',
             'checks':{'attribution':'valid','segmentation':'usable','context':'sufficient'},
             'values':{k:'unresolved' for k in blind['fields']},
             'evidence_ids':[blind['source']['id'],blind['subject']['id']],'rationale':'Synthetic validation, not ground truth.'}
        validate_annotation(row,blind,'manifest')
        row['evidence_ids'].append('missing-source')
        with self.assertRaises(InputError):validate_annotation(row,blind,'manifest')

    def test_normalized_rollout_projection_preserves_exact_prefix_without_final_outcomes(self):
        from tracker.activity import units
        run=bundle()['run'];eligible=[u for u in units(run) if u['eligible']]
        a,b=eligible[:2]
        prefix,source,subject=rollout_evidence(run,a['id'],b['id'])
        request=packet(prefix,source,subject)
        self.assertEqual(request['state']['subject']['text'],b['text'])
        self.assertNotIn('HIDDEN-GRADE',json.dumps(request));self.assertNotIn('HIDDEN-POLICY',json.dumps(request))
        self.assertEqual(len(prefix[-1]['text']),b['end'])
        self.assertEqual(source['trace_id'],run['id'])


if __name__=='__main__':unittest.main()
