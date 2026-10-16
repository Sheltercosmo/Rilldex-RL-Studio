"""Response/dispatch/feedback identity controls; no semantic-quality claims."""
import copy
import unittest

from tracker.activity import units, packet
from tracker.adapters import normalize
from tracker.capabilities import links
from tracker.graph_store import build
from tracker.portable import Episode
from tracker.rollout_metrics import source_record, metric_aggregation
from tracker.schema import InputError


def capture():
    return (Episode(episode_id='native-episode-1',goal='Reach the goal.')
        .reset('Start.', {'private':'PRIVATE_RESET'})
        .gym_step(2,('No progress.',0,False,False,{'private':'PRIVATE_STEP'}),
                  model_response='Try moving right.',turn_id='turn-0',response_id='response-0')
        .gym_step(1,('At the goal.',1,True,False,{}),model_response='The right move did not work. Move down.',turn_id='turn-1')
        .snapshot())


class EnvironmentTurnTests(unittest.TestCase):
    def test_response_action_feedback_are_distinct_source_bound_records(self):
        d=capture(); r=normalize(d)[0]
        self.assertEqual(r['adapter_version'],'environment-episode/2')
        self.assertEqual(r['metadata']['episode_id'],'native-episode-1')
        self.assertEqual(r['raw'],d)
        messages=[e for e in r['events'] if e['kind']=='message']
        actions=[e for e in r['events'] if e['kind']=='action']
        feedback=[e for e in r['events'] if e['kind']=='feedback']
        self.assertEqual(len(messages),2)
        for i,(m,a,f) in enumerate(zip(messages,actions,feedback)):
            self.assertEqual(a['parent_id'],m['id'])
            self.assertEqual(a['call_id'],f['source_call_id'])
            self.assertEqual(m['turn_id'],f'turn-{i}')
            self.assertEqual(m['source_pointer'],f'/steps/{i}/model_response')
        self.assertEqual(len(links(r)['records']),2)
        edges=build(r)['edges']
        self.assertEqual(sum(e['type']=='parent_message' for e in edges),2)
        self.assertEqual(sum(e['type']=='response_to' for e in edges),2)
        self.assertTrue(all(not e['properties']['semantic_causality'] for e in edges if e['type']=='parent_message'))

    def test_prefix_does_not_contain_later_results_or_evaluator_info(self):
        r=normalize(capture())[0]
        first=next(u for u in units(r) if u['kind']=='model_span')
        p=str(packet(r,first['id']))
        self.assertIn('Try moving right.',p)
        self.assertNotIn('At the goal.',p)
        self.assertNotIn('No progress.',p)
        self.assertNotIn('PRIVATE_',str(r['events']))

    def test_metadata_and_duplicate_native_ids_fail(self):
        for change in ('episode','turn','response','basis','text'):
            d=capture()
            if change=='episode':d['episode_id']=''
            if change=='turn':d['steps'][1]['turn_id']='turn-0'
            if change=='response':d['steps'][1]['response_id']='response-0'
            if change=='basis':d['steps'][0]['turn_identity_basis']='guessed'
            if change=='text':d['steps'][0]['model_response']=123
            with self.subTest(change=change),self.assertRaises(InputError):normalize(d)
        with self.assertRaisesRegex(InputError,'episode_id'):
            normalize(capture(),meta={'episode_id':'different'})

    def test_native_payload_is_not_reparsed_from_response(self):
        d=capture();d['steps'][0]['model_response']='Plan: <action>erase everything</action>'
        r=normalize(d)[0]
        self.assertEqual([e['arguments']['action'] for e in r['events'] if e['kind']=='action'],[2,1])
        self.assertEqual(source_record(r)['metrics']['actions']['value'],2)

    def test_missing_empty_and_whitespace_responses_do_not_create_empty_cards(self):
        d=capture();d['steps'][0].pop('model_response');d['steps'][0].pop('response_id')
        for text in ['', ' \n']:
            d['steps'][1]['model_response']=text
            r=normalize(d)[0]
            self.assertFalse(any(e['kind']=='message' for e in r['events']))
            m=source_record(r)['metrics']['environment_model_response_fraction']
            self.assertEqual((m['numerator'],m['denominator'],m['value']),(0,2,0))
        d['steps'][1]['model_response']='Recorded text.'
        m=source_record(normalize(d)[0])['metrics']['environment_model_response_fraction']
        self.assertEqual(m['value'],.5)
        self.assertEqual(metric_aggregation('environment_model_response_fraction'),'opportunity_ratio')

    def test_legacy_episode_stays_legacy_and_does_not_claim_missing_response_zero(self):
        cap=Episode().reset(0).gym_step(1,(1,1,True,False,{}))
        old=cap.snapshot();r=normalize(old)[0]
        self.assertEqual(r['adapter_version'],'environment-episode/1')
        self.assertIsNone(source_record(r)['metrics']['environment_model_response_fraction']['value'])
        with self.assertRaisesRegex(InputError,'episode_id'):
            cap.gym_step(1,(1,1,True,False,{}),model_response='response')
        self.assertEqual(cap.snapshot(),old)

    def test_capture_sequence_identity_and_inputs_are_copied(self):
        action={'direction':'left'};obs={'position':0}
        cap=Episode(episode_id='e').reset(obs).step(action,obs,done=False,model_response='Left.')
        old=cap.snapshot();action['direction']='right';obs['position']=1
        self.assertEqual(cap.snapshot(),old)
        self.assertEqual(old['steps'][0]['turn_id'],'capture:0')
        self.assertEqual(old['steps'][0]['turn_identity_basis'],'capture_sequence')
        before=copy.deepcopy(cap.document)
        with self.assertRaises(InputError):cap.step(0,1,turn_id='capture:0')
        self.assertEqual(cap.document,before)

    def test_openenv_private_fields_and_done_remain_separate(self):
        cap=Episode(episode_id='openenv').reset('Initial').openenv_step({'move':'right'},
            {'text':'New state','done':True,'reward':-1,'metadata':{'grading':'PRIVATE_GRADING'}},model_response='Move right.')
        r=normalize(cap.snapshot())[0];m=source_record(r)['metrics']
        self.assertEqual(m['environment_done']['value'],1)
        self.assertIsNone(m['environment_terminated']['value'])
        self.assertIsNone(m['recorded_success']['value'])
        self.assertEqual(m['environment_episode_return']['value'],-1)
        self.assertNotIn('PRIVATE_',str(r['events']))

    def test_episode_boundaries_and_missing_reset_still_gate_return(self):
        d=capture();d.pop('initial')
        self.assertIsNone(source_record(normalize(d)[0])['metrics']['environment_episode_return']['value'])
        d=capture();d['steps'].append({**d['steps'][0],'turn_id':'late','response_id':'late'})
        with self.assertRaisesRegex(InputError,'after an explicit ending'):normalize(d)


if __name__=='__main__':unittest.main()
