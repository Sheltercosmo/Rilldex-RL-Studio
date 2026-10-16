"""Native source fidelity tests; small authored edge cases are explicitly synthetic."""
import copy
import hashlib
import json
from pathlib import Path
import unittest

from tracker.activity import units, packet
from tracker.adapters import normalize
from tracker.capabilities import links
from tracker.graph_store import build
from tracker.rollout_metrics import source_record
from tracker.schema import InputError, digest

FIXTURES=Path(__file__).parent/'fixtures/tau-bench'


def call(cid='a',who='assistant'):
    return {'id':cid,'name':'lookup','arguments':{'item':cid},'requestor':who}


def response(cid='a',who='assistant',text='result'):
    return {'role':'tool','id':cid,'requestor':who,'content':text,'error':False}


def simulation(messages=None):
    return {'id':'synthetic-1','task_id':'task-1','termination_reason':'max_steps',
        'messages':messages if messages is not None else [
            {'role':'assistant','content':None,'tool_calls':[call()]},response(),
            {'role':'assistant','content':'The record is available.'}],
        'trial':0,'seed':42,'reward_info':{'reward':0,'info':'SECRET_EVALUATOR'}}


def bundle():
    return {'info':{'git_commit':'source-commit','environment_info':{'domain_name':'example','policy':'Follow recorded policy.'},
        'agent_info':{'llm':'test'},'user_info':{'global_simulation_guidelines':'SECRET_USER'}},
        'tasks':[{'id':'task-1','evaluation_criteria':'SECRET_CRITERIA','initial_state':'SECRET_STATE'}],
        'simulations':[simulation(),dict(simulation(),id='synthetic-2')]}


def pointer(doc,path):
    for part in path.split('/')[1:]:
        key=part.replace('~1','/').replace('~0','~')
        doc=doc[int(key)] if isinstance(doc,list) else doc[key]
    return doc


class TauBenchTests(unittest.TestCase):
    def test_standalone_user_termination_markers_are_protocol_controls(self):
        from tracker.semantic_extraction import windows
        for marker in ('###STOP###','###TRANSFER###','###OUT-OF-SCOPE###'):
            text='  '+marker+'\n'
            run=normalize(simulation([{'role':'user','content':text}]))[0]
            e=run['events'][0]
            self.assertEqual(e['kind'],'control')
            self.assertEqual(e['actor'],'user')
            self.assertEqual(e['text'],text)
            self.assertEqual(e['protocol_markers'],[marker])
            self.assertEqual(windows(run,include_user=True),[])
            self.assertEqual(pointer(run['raw'],e['source_pointer']),text)
            self.assertEqual(build(run)['counts']['unresolved_endpoints'],0)
            self.assertEqual(run['adapter_version'],'tau-bench/2')

    def test_marker_with_real_text_retains_user_contribution(self):
        from tracker.semantic_extraction import windows
        text='Thanks for checking. ###STOP###'
        run=normalize(simulation([{'role':'user','content':text}]))[0]
        self.assertEqual(run['events'][0]['kind'],'instruction')
        self.assertEqual(run['events'][0]['protocol_markers'],['###STOP###'])
        self.assertEqual([w['text'] for w in windows(run,include_user=True)],[text])

    def test_repeated_control_markers_do_not_create_work(self):
        from tracker.semantic_extraction import windows
        text='###STOP###\n ###STOP### ###TRANSFER###'
        run=normalize(simulation([{'role':'user','content':text}]))[0]
        self.assertEqual(run['events'][0]['kind'],'control')
        self.assertEqual(run['events'][0]['text'],text)
        self.assertEqual(windows(run,include_user=True),[])

    def test_other_roles_and_user_tool_calls_do_not_become_termination_controls(self):
        for message in [{'role':'assistant','content':'###STOP###'},
                        {'role':'user','content':'###STOP###','tool_calls':[call('x','user')]}]:
            run=normalize(simulation([message]))[0]
            self.assertNotEqual(run['events'][0]['kind'],'control')
            self.assertNotIn('protocol_markers',run['events'][0])

    def test_pinned_public_fragments_preserve_calls_text_rewards_and_pointers(self):
        manifest=json.loads((FIXTURES/'sources.json').read_text())
        for item in manifest['fixtures']:
            raw=(FIXTURES/item['file']).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(),item['sha256'])
            doc=json.loads(raw);sim=doc['simulation'];run=normalize(doc)[0]
            original_agent=[c for m in sim['messages'] if m['role']=='assistant' for c in m.get('tool_calls') or []]
            original_user=[c for m in sim['messages'] if m['role']=='user' for c in m.get('tool_calls') or []]
            for kind,original in [('action',original_agent),('external_action',original_user)]:
                events=[e for e in run['events'] if e['kind']==kind]
                self.assertEqual(len(events),len(original))
                for e,c in zip(events,original):
                    self.assertEqual(pointer(doc,e['source_pointer']),c)
                    self.assertEqual((e['native_call_id'],e['tool'],e['arguments']),(c['id'],c['name'],c['arguments']))
            for e in run['events']:
                if e['kind'] not in {'action','external_action'}:
                    self.assertEqual(e['text'],pointer(doc,e['source_pointer']) or '')
            m=source_record(run)['metrics']
            self.assertEqual(m['recorded_reward']['value'],sim['reward_info']['reward'])
            self.assertEqual(m['actions']['value'],len(original_agent))
            self.assertIsNone(m['recorded_success']['value'])
            self.assertNotIn('training_step',run['metadata'])
            self.assertNotIn('policy_version',run['metadata'])

    def test_bundle_keeps_trial_identity_and_projects_exact_relevant_source(self):
        doc=bundle();runs=normalize(doc)
        self.assertEqual(len({r['id'] for r in runs}),2)
        self.assertEqual(runs,normalize(doc))
        for i,r in enumerate(runs):
            self.assertEqual(r['raw']['simulation'],doc['simulations'][i])
            self.assertEqual(r['raw']['task'],doc['tasks'][0])
            self.assertEqual(r['raw']['info'],doc['info'])
            self.assertEqual(r['raw']['source_origin']['collection_sha256'],digest(doc))
            self.assertEqual(r['raw']['source_origin']['simulation_pointer'],f'/simulations/{i}')
            self.assertNotIn('simulations',r['raw'])
            self.assertEqual(r['metadata']['task_revision'],'source-commit')

    def test_bundle_rejects_duplicate_or_missing_identity(self):
        for change in ('duplicate_sim','missing_task','duplicate_task','wrong_envelope'):
            doc=bundle()
            if change=='duplicate_sim':doc['simulations'][1]['id']=doc['simulations'][0]['id']
            if change=='missing_task':doc['simulations'][1]['task_id']='absent'
            if change=='duplicate_task':doc['tasks'].append(doc['tasks'][0])
            if change=='wrong_envelope':
                doc=normalize(doc)[0]['raw'];doc['task']={'id':'wrong'}
            with self.assertRaises(InputError,msg=change):normalize(doc)

    def test_private_user_tools_stay_external_and_never_reach_agent_packets(self):
        doc=bundle();doc['simulations']=[simulation([
            {'role':'user','content':'SECRET_USER_THOUGHT','tool_calls':[call('a','user')]},
            response('a','user','SECRET_USER_RESULT'),
            {'role':'user','content':'I changed my setting.'},
            {'role':'assistant','content':'I will look at the account.','raw_data':{'hidden':'SECRET_RAW'},'tool_calls':[call('a')]},
            response('a',text='Visible account'),{'role':'assistant','content':'The account is ready.'}])]
        run=normalize(doc)[0];bound=links(run)
        self.assertEqual(len(bound['records']),1)
        self.assertEqual(sum(e['kind']=='external_action' for e in run['events']),1)
        for u in units(run):
            if u['eligible']:self.assertNotIn('SECRET',str(packet(run,u['id'])))
        self.assertNotIn('SECRET_RAW',str(run['events']))
        self.assertEqual(sum(e['type']=='response_to' for e in build(run)['edges']),1)

    def test_parallel_multitool_results_and_reused_id_bind_pending_call_only(self):
        doc=simulation([
            {'role':'assistant','content':None,'tool_calls':[call('a'),call('b')]},
            {'role':'tool','tool_messages':[response('b',text='B'),response('a',text='A')]},
            {'role':'assistant','content':None,'tool_calls':[call('a')]},response('a',text='A2')])
        run=normalize(doc)[0];actions=[e for e in run['events'] if e['kind']=='action'];bound=links(run)
        self.assertEqual([bound['by_action'][a['id']][0]['text'] for a in actions],['A','B','A2'])
        self.assertEqual(len({a['call_id'] for a in actions}),3)

    def test_ambiguous_missing_and_unanswered_calls_do_not_gain_false_links(self):
        for calls,responses in [([call('a'),call('a')],[response('a')]),([call('')],[response('')]),([call('a')],[response('b')]),([call('a')],[])]:
            run=normalize(simulation([{'role':'assistant','content':None,'tool_calls':calls},*responses]))[0]
            self.assertEqual(links(run)['records'],[])
            self.assertEqual(source_record(run)['metrics']['actions']['value'],len(calls))

    def test_native_error_is_preserved_without_global_failure_inference(self):
        doc=simulation();doc['messages'][1]['error']=True
        run=normalize(doc)[0]
        self.assertTrue(next(e for e in run['events'] if e['kind']=='feedback')['reported_tool_error'])
        self.assertIsNone(source_record(run)['metrics']['recorded_success']['value'])

    def test_unknown_reward_missing_config_and_explicit_environment(self):
        doc=simulation();doc['reward_info']=None
        run=normalize(doc,meta={'environment':'tau-bench/custom'})[0]
        self.assertEqual(run['metadata']['environment'],'tau-bench/custom')
        self.assertIsNone(source_record(run)['metrics']['recorded_reward']['value'])
        self.assertTrue(any('No native tool definitions' in w for w in run['warnings']))
        with self.assertRaisesRegex(InputError,'conflicts'):normalize(bundle(),meta={'environment':'wrong'})

    def test_tool_contract_has_exact_source_and_unique_names(self):
        doc=bundle();tool={'type':'function','function':{'name':'lookup','parameters':{'type':'object'}}}
        doc['info']['environment_info']['tool_defs']=[tool]
        r=normalize(doc)[0];a=next(e for e in r['events'] if e['kind']=='action')
        self.assertEqual(pointer(r['raw'],a['tool_contract']['source_pointer']),tool)
        doc['info']['environment_info']['tool_defs'].append(tool)
        with self.assertRaisesRegex(InputError,'Duplicate'):normalize(doc)

    def test_voice_malformed_and_conflicting_records_are_rejected(self):
        for change in ('ticks','audio','nested_audio','requestor','arguments','reward','domain','error'):
            doc=bundle();sim=doc['simulations'][0]
            if change=='ticks':sim['ticks']=[{'audio':'bytes'}]
            if change=='audio':sim['messages'][0]['chunk_id']=0
            if change=='nested_audio':sim['messages'][1]={'role':'tool','tool_messages':[dict(response(),is_audio=True)]}
            if change=='requestor':sim['messages'][0]['tool_calls'][0]['requestor']='user'
            if change=='arguments':sim['messages'][0]['tool_calls'][0]['arguments']='{}'
            if change=='reward':sim['reward_info']['reward']=True
            if change=='domain':doc['info']['environment_info']['domain_name']=[]
            if change=='error':sim['messages'][1]['error']='false'
            with self.assertRaises(InputError,msg=change):normalize(doc)


if __name__=='__main__':unittest.main()
