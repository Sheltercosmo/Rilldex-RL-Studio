"""Contract regressions, authored cases unless a pinned public fixture is named."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from tracker.activity import packet, units
from tracker.adapters import normalize
from tracker.capabilities import links
from tracker.graph_store import build
from tracker.integrations import check
from tracker.portable import Episode, chat_document, generation_document
from tracker.rollout_metrics import source_record, report, save, VERSION
from tracker.schema import InputError
from tracker.store import Store


def conversation():
    return chat_document([
        {'role':'developer','content':'Use only visible evidence.'},
        {'role':'user','content':'Compare two records.'},
        {'role':'assistant','content':None,'reasoning_content':'I need both records.',
         'tool_calls':[{'id':cid,'type':'function','function':{'name':'read','arguments':{'id':cid}}} for cid in ('a','b')]},
        {'role':'tool','tool_call_id':'b','content':'Record B'},
        {'role':'tool','tool_call_id':'a','content':'Record A'},
        {'role':'assistant','content':'They differ.'}],reward=0,success=False)


def episode():
    return Episode(metadata={'experiment':'contract','training_step':2,'training_step_basis':'generation_iteration'},goal='Reach the goal.').reset(0,{'private':'SECRET_RESET'}).gym_step(2,(1,.5,False,False,{'private':'SECRET_INFO'})).gym_step(2,(2,1,True,False,{})).snapshot()


class PortableTests(unittest.TestCase):
    def test_parallel_calls_follow_ids_not_result_order(self):
        run=normalize(conversation())[0];joined=links(run)
        actions={e['call_id']:e for e in run['events'] if e['kind']=='action'}
        self.assertEqual(joined['by_action'][actions['a']['id']][0]['text'],'Record A')
        self.assertEqual(joined['by_action'][actions['b']['id']][0]['text'],'Record B')
        self.assertEqual(actions['a']['text'],'read({"id": "a"})')
        self.assertEqual(len([e for e in build(run)['edges'] if e['type']=='response_to']),2)
        self.assertEqual(source_record(run)['metrics']['recorded_success']['value'],0)

    def test_missing_ids_never_make_a_proximity_link(self):
        doc=conversation()
        for c in doc['messages'][2]['tool_calls']:del c['id']
        for m in doc['messages'][3:5]:del m['tool_call_id']
        run=normalize(doc)[0]
        self.assertEqual(len(links(run)['records']),0)
        self.assertEqual(len(links(run)['unlinked_ids']),2)
        self.assertEqual(sum(e['kind']=='feedback' for e in run['events']),2)

    def test_invalid_arguments_are_evidence_but_duplicate_ids_rejected(self):
        doc=conversation();doc['messages'][2]['tool_calls'][0]['function']['arguments']='{bad'
        run=normalize(doc)[0]
        self.assertEqual(next(e for e in run['events'] if e['kind']=='action')['argument_status'],'invalid_json_object')
        doc['messages'][2]['tool_calls'][1]['id']='a'
        with self.assertRaises(InputError):normalize(doc)

    def test_media_is_preserved_and_not_claimed_inspected(self):
        doc=conversation();doc['messages'][3]['content']=[{'type':'text','text':'Visible caption'},{'type':'image_url','image_url':{'url':'asset://screen.png'}}]
        result=check({'document':doc})['runs'][0]
        self.assertEqual(next(f for f in result['functions'] if f['name']=='Visual / audio behavior')['state'],'uninspected')
        doc['messages'][3]['content']=['silently dropped?']
        with self.assertRaises(InputError):normalize(doc)

    def test_private_evaluation_and_later_feedback_do_not_leak(self):
        doc=conversation();doc['outcome']['grading_note']='SECRET_GRADE';doc['ground_truth']='SECRET_TARGET'
        run=normalize(doc)[0]
        for u in units(run):
            if not u['eligible']:continue
            p=str(packet(run,u['id']))
            self.assertNotIn('SECRET',p)
            if u['kind']=='action_dispatch':self.assertNotIn('Record A',p)

    def test_environment_flags_return_and_private_info(self):
        run=normalize(episode())[0];m=source_record(run)['metrics']
        self.assertEqual(m['environment_steps']['value'],2)
        self.assertEqual(m['environment_episode_return']['value'],1.5)
        self.assertEqual(m['environment_terminated']['value'],1)
        self.assertEqual(m['environment_truncated']['value'],0)
        self.assertEqual(m['environment_done']['value'],1)
        self.assertIsNone(m['recorded_success']['value'])
        self.assertIsNone(m['recorded_reward']['value'])
        self.assertEqual(m['environment_episode_return']['evidence_ids'],['/steps/0/reward','/steps/1/reward'])
        self.assertEqual(len(links(run)['records']),2)
        self.assertNotIn('SECRET',str(run['events']))
        for u in units(run):
            if u['eligible']:self.assertNotIn('SECRET',str(packet(run,u['id'])))

    def test_partial_missing_rewards_and_missing_reset_are_unknown_returns(self):
        for change in ('partial','reward','reset'):
            doc=episode()
            if change=='partial':doc['steps'].pop()
            if change=='reward':doc['steps'][0]['reward']=None
            if change=='reset':del doc['initial']
            self.assertIsNone(source_record(normalize(doc)[0])['metrics']['environment_episode_return']['value'],change)

    def test_truncation_is_not_failure_and_openenv_done_not_termination(self):
        doc=episode();doc['steps'][-1].update(terminated=False,truncated=True)
        m=source_record(normalize(doc)[0])['metrics']
        self.assertEqual(m['environment_truncated']['value'],1);self.assertIsNone(m['recorded_success']['value'])
        doc=Episode().reset('initial').openenv_step({'command':'look'},{'text':'visible','reward':-1,'done':True,'metadata':{'hidden':'SECRET'}}).snapshot()
        run=normalize(doc)[0];m=source_record(run)['metrics']
        self.assertEqual(m['environment_done']['value'],1);self.assertEqual(m['environment_episode_return']['value'],-1)
        self.assertIsNone(m['environment_terminated']['value']);self.assertIsNone(m['environment_truncated']['value'])
        self.assertNotIn('SECRET',str(run['events']))

    def test_invalid_transition_semantics_fail_before_storage(self):
        for key,value in [('done',True),('terminated','yes'),('reward',float('nan'))]:
            doc=episode();doc['steps'][0][key]=value
            with self.assertRaises(InputError):normalize(doc)
        doc=episode();doc['steps'][0]['terminated']=True
        with self.assertRaisesRegex(InputError,'after an explicit ending'):normalize(doc)
        doc=episode();del doc['steps'][0]['truncated']
        with self.assertRaises(InputError):normalize(doc)

    def test_return_overflow_is_unknown(self):
        doc=episode()
        for s in doc['steps']:s['reward']=1.7e308
        self.assertIsNone(source_record(normalize(doc)[0])['metrics']['environment_episode_return']['value'])

    def test_generation_does_not_invent_tools_clock_or_success(self):
        doc=generation_document('Question','<tool_call>search(answer)</tool_call>',reward=1)
        run=normalize(doc)[0];m=source_record(run)['metrics']
        self.assertIsNone(m['actions']['value']);self.assertIsNone(m['recorded_success']['value'])
        self.assertEqual(m['recorded_reward']['value'],1);self.assertNotIn('training_step',run['metadata'])
        self.assertEqual(len(run['events']),2)

    def test_conflicting_clock_and_nontext_tokens_are_rejected(self):
        doc=generation_document('p','c',metadata={'generation_step':8,'learner_step':10,'training_step':8,'training_step_basis':'generation_iteration'})
        with self.assertRaisesRegex(InputError,'Conflicting'):normalize(doc,meta={'generation_step':10})
        doc['completion']=[123,456]
        with self.assertRaisesRegex(InputError,'token IDs'):normalize(doc)

    def test_atif_alias_replays_pinned_public_trajectory(self):
        path=Path(__file__).parent/'fixtures/harbor/hello-world-timeout.trajectory.json'
        doc=json.loads(path.read_text(encoding='utf-8'));a=normalize(doc,'harbor')[0];b=normalize(doc,'atif')[0]
        self.assertEqual(a['events'],b['events']);self.assertEqual(b['adapter_version'],'atif/1')

    def test_preflight_is_evidence_availability_not_a_semantic_verdict(self):
        result=check({'document':episode()})
        self.assertFalse(result['persisted']);row=result['runs'][0]
        self.assertEqual(row['linked_responses'],2)
        self.assertEqual(next(f for f in row['functions'] if f['name'].startswith('Semantic'))['state'],'needs_analysis')
        self.assertEqual(next(f for f in row['functions'] if f['name'].startswith('Training'))['state'],'declared')
        self.assertNotIn('policy_version',row['clocks'])

    def test_visible_environment_instructions_are_explicit_and_private_info_stays_out(self):
        doc=Episode(goal='Navigate.',visible_context={'actions':{'2':'right'}}).reset(0,{'answer':'SECRET'}).gym_step(2,(1,0,True,False,{})).snapshot()
        run=normalize(doc)[0]
        context=next(e for e in run['events'] if e['source_pointer']=='/visible_context')
        self.assertIn('right',context['text']);self.assertNotIn('SECRET',str(run['events']))

    def test_cli_preflight_never_opens_a_database(self):
        from contextlib import redirect_stdout
        import io
        from unittest.mock import patch
        from tracker.cli import main
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'episode.json';path.write_text(json.dumps(episode()))
            output=io.StringIO()
            with patch('sys.argv',['tracker','check',str(path)]),patch('tracker.cli.Store',side_effect=AssertionError('Database opened')),redirect_stdout(output):main()
            self.assertFalse(json.loads(output.getvalue())['persisted'])

    def test_revisions_monitors_and_explanation_keep_exact_source(self):
        from tracker import monitoring, monitor_evidence
        from tracker.failure_investigations import SOURCE_KEYS
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'tracker.sqlite');doc=episode();partial=copy.deepcopy(doc);partial['steps'].pop()
            p={'producer':'portable-test','rollout_id':'a','revision':0,'state':'in_progress','document':partial}
            old=store.ingest(p);p.update(revision=1,state='complete',document=doc);final=store.ingest(p)
            mon=monitoring.create(store,{'name':'Return','kind':'metric','metric':'environment_episode_return','observer':'source'})
            monitoring.sync(store)
            with store.connect() as c:vid=c.execute('SELECT value_id FROM monitor_latest WHERE monitor_id=? AND run_id=?',(mon['id'],final['id'])).fetchone()[0]
            proof=monitor_evidence.read(store,vid)
            self.assertEqual(proof['measurement']['value'],1.5)
            self.assertEqual([v['value'] for v in proof['explanation']['source_values']],[.5,1])
            self.assertEqual(len(store.lineage(final['id'])['history']),2)
            self.assertFalse(store.get(old['id'])['ingestion']['is_latest'])
            self.assertIn('environment_episode_return',SOURCE_KEYS)

    def test_v15_extension_keeps_prior_measurement_immutable(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'tracker.sqlite');run=normalize(episode())[0];store.add([run])
            old=source_record(run);old['schema']='rollout-behavior/15';old['observer']='legacy-observer';old['annotation_hash']='retained'
            for key in list(old['metrics']):
                if key.startswith('environment_'):del old['metrics'][key]
            with store.connect() as c:oldid=save(c,old)
            current=next(r for r in report(store)['rows'] if r['observer']=='legacy-observer')
            self.assertEqual(current['schema'],VERSION);self.assertEqual(current['metrics']['environment_episode_return']['value'],1.5)
            with store.connect() as c:self.assertEqual(json.loads(c.execute('SELECT document FROM rollout_measurements WHERE id=?',(oldid,)).fetchone()[0]),old)


if __name__=='__main__':unittest.main()
