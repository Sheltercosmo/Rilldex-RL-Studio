"""Context retrieval, source isolation and useful decisions with long manuals."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.evaluate_reading_context import cases, requests, evaluate, score
from tracker.adapters import normalize
from tracker.jev import packet, validate_answers
from tracker.schema import InputError, digest, dumps
from test_tracker import response_for
from scripts.evaluate_feedback_reading import cases as feedback_cases


def distant():
    case = next(c for c in cases() if c['id']=='inventory-blocked-distant')
    run = normalize(case['document'])[0]
    return run, [e for e in run['events'] if e['kind']=='action'][-1]


class ActionContextTests(unittest.TestCase):
    def test_long_recent_results_retain_endings_without_blocking_the_next_response(self):
        for case in feedback_cases():
            if case['kind'] != 'authored':continue
            with self.subTest(case=case['id'], format=case['format']):
                run=normalize(case['document'])[0]
                action=[e for e in run['events'] if e['kind']=='action'][-1]
                req=packet(run,action['id'])
                result=validate_answers(response_for(req),req)
                self.assertEqual(result['feedback_response']['status'],'decided')
                for entry in req['state']['prior_actions']:
                    for feedback in entry['feedback']:
                        source=next(e for e in run['events'] if e['id']==feedback['event_id'])
                        if len(source['text'])<=3000:continue
                        self.assertIn(source['text'][-200:],feedback['text'])
                        self.assertTrue(feedback['omitted_text_ranges'])
                        self.assertLess(len(feedback['text']),5000)
                        for ref in feedback['source_text_ranges']:
                            self.assertEqual(source['text'][ref['source_start']:ref['source_end']],
                                feedback['text'][ref['view_start']:ref['view_end']])

    def test_recent_result_keeps_matched_middle_and_later_correction(self):
        case=next(c for c in feedback_cases() if c['id']=='navigation-immediate' and c['format']=='chat')
        run=normalize(case['document'])[0]
        action=[e for e in run['events'] if e['kind']=='action'][-1]
        feedback=next(e for e in run['events'] if e['kind']=='feedback')
        marker='parcel P7 destination pier B bridge is closed'
        feedback['text']='diagnostic sample 0\n'*300+marker+'\n'+'diagnostic sample 1\n'*300+'Correction: bridge is open now.'
        req=packet(run,action['id'])
        viewed=req['state']['prior_actions'][-1]['feedback'][0]
        self.assertIn(marker,viewed['text'])
        self.assertIn('Correction: bridge is open now.',viewed['text'])

    def test_only_adjacent_dispatch_clipping_blocks_its_response_comparison(self):
        case=next(c for c in feedback_cases() if c['id']=='service-older' and c['format']=='chat')
        for previous in (0,1):
            run=normalize(case['document'])[0]
            actions=[e for e in run['events'] if e['kind']=='action']
            actions[previous]['text']+=' x'*2000
            req=packet(run,actions[-1]['id'])
            result=validate_answers(response_for(req),req)
            self.assertEqual(result['feedback_response']['status'],'decided' if previous==0 else 'unresolved')

    def test_retrieves_distant_state_without_rewriting_recent_action_order(self):
        run, action = distant(); original = deepcopy(run)
        req = packet(run, action['id'])
        old = req['state']['earlier_relevant_actions']
        self.assertEqual(len(old), 1)
        self.assertIn('"available":3', old[0]['feedback'][0]['text'])
        self.assertEqual(old[0]['feedback'][0]['source_pointer'], '/messages/2/content')
        self.assertNotIn('available', dumps(req['state']['prior_actions']))
        self.assertEqual(req['state']['prior_actions'][-1]['action']['event_id'],
                         [e for e in run['events'] if e['kind']=='action'][-2]['id'])
        self.assertEqual(run, original)

    def test_retrieval_does_not_require_known_tool_names(self):
        run, action = distant()
        for e in run['events']:
            if e['kind']=='action':
                name=e['tool'];e['tool']='接口';e['text']=e['text'].replace(name, '接口')
        feedback=[f['text'] for entry in packet(run, action['id'])['state']['earlier_relevant_actions'] for f in entry['feedback']]
        self.assertTrue(any('"available":3' in text for text in feedback))

    def test_other_contexts_private_copied_and_unknown_order_are_not_retrieved(self):
        for field, value in [('context_id','other'), ('trajectory_id','other'),
                ('agent_visibility','not_established'), ('agent_visible',False),
                ('copied_context',True), ('order_known',False)]:
            run, action=distant()
            first=next(e for e in run['events'] if e['kind']=='action')
            feedback=next(e for e in run['events'] if e.get('source_call_id')==first['call_id'])
            for e in (first, feedback):e[field]=value
            with self.subTest(field=field):
                req=packet(run,action['id'])
                selected=[f['event_id'] for entry in req['state']['prior_actions']+req['state']['earlier_relevant_actions'] for f in entry['feedback']]
                self.assertNotIn(feedback['id'],selected)

    def test_future_feedback_and_outcomes_do_not_change_retrieval(self):
        run, action=distant(); before=packet(run,action['id'])
        run['outcome']['recorded_reward']='PRIVATE_FINAL_REWARD'
        run['events'].append({'id':'future','index':action['index']+1,'trajectory_id':'main',
            'kind':'feedback','actor':'tool','text':'FUTURE_STATE A7 available 1000',
            'source_pointer':'/future','source_call_id':'c0','copied_context':False})
        self.assertEqual(before, packet(run,action['id']))

    def test_latest_state_is_preserved_alongside_older_state(self):
        case=next(c for c in cases() if c['id']=='inventory-state-updated')
        run=normalize(case['document'])[0];action=[e for e in run['events'] if e['kind']=='action'][-1]
        req=packet(run,action['id'])
        self.assertIn('"available":8', req['state']['prior_actions'][-1]['feedback'][0]['text'])
        self.assertIn('source order',req['state']['context_retrieval']['scope'])

    def test_long_result_preserves_matched_passage_with_exact_offsets(self):
        run,action=distant()
        feedback=next(e for e in run['events'] if e['kind']=='feedback')
        feedback['text']='unrelated readings '*500+'SKU A7 available stock is 3.'+' diagnostics '*500
        req=packet(run,action['id'])
        result=req['state']['earlier_relevant_actions'][0]['feedback'][0]
        self.assertIn('SKU A7 available stock is 3.',result['text'])
        self.assertTrue(result['omitted_text_ranges'])
        for r in result['source_text_ranges']:
            self.assertEqual(feedback['text'][r['source_start']:r['source_end']],
                             result['text'][r['view_start']:r['view_end']])
        self.assertLess(len(result['text']),5000)
        self.assertEqual(req['state']['missingness']['required_truncated_by_question']['mode'],[])

    def test_long_manual_is_complete_for_public_trace_examples(self):
        for name in ('airline-0','telecom-0'):
            raw=json.loads((Path(__file__).parent/'fixtures/tau-bench'/(name+'.json')).read_text(encoding='utf-8'))
            run=normalize(raw)[0];action=next(e for e in run['events'] if e['kind']=='action')
            req=packet(run,action['id']);context=req['state']['harness_context'][0]
            self.assertEqual(context['text'],run['events'][0]['text'])
            self.assertNotIn('e1',req['state']['missingness']['truncated_event_ids'])

    def test_oversized_policy_does_not_discard_unrelated_purpose_decisions(self):
        run, action=distant()
        run['events'].insert(0, {'id':'policy','index':-1,'trajectory_id':'main',
            'kind':'context','actor':'system','text':'policy '*4000,'source_pointer':'/system','copied_context':False})
        req=packet(run,action['id']); result=validate_answers(response_for(req),req)
        self.assertEqual(result['mode']['status'],'decided')
        self.assertEqual(result['goal_relation']['status'],'unresolved')
        self.assertIn('policy',req['state']['missingness']['required_truncated_by_question']['goal_relation'])

    def test_current_action_clipping_still_affects_all_dependent_questions(self):
        run,action=distant();action['text']+=' x'*4000
        req=packet(run,action['id']);result=validate_answers(response_for(req),req)
        for key in req['questions']:
            self.assertEqual(result[key]['status'],'unresolved',key)

    def test_ablation_keeps_references_and_later_evidence_out_of_requests(self):
        rows=list(requests('jev-1.13.0',['current','complete_prefix']))
        self.assertEqual(len(rows),56)
        for row in rows:
            self.assertNotIn('reference',row['request'])
            self.assertNotIn('outcome',row['request']['state'])
            self.assertEqual(row['request_hash'],digest(row['request']))
        with tempfile.TemporaryDirectory() as temp:
            result=evaluate(temp)
            self.assertEqual(result['status'],'requests_only')
            self.assertFalse(result['groups'])

    def test_evaluation_scores_delivered_status_and_validates_model(self):
        row=next(requests('jev-1.13.0',['current']))
        response=response_for(row['request']);response['model']='wrong-model'
        with self.assertRaises(InputError):score(response,row)
        response['model']='jev-1.13.0'
        row['request']['state']['missingness']['required_truncated_by_question']['mode']=['action']
        self.assertEqual(score(response,row)['mode']['prediction'],'unresolved')


if __name__=='__main__':unittest.main()
