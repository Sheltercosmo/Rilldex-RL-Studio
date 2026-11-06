"""Native scope, bounded definitions and frozen requirement replay controls.

Scripted selections test evidence plumbing, not semantic model accuracy.
"""
import argparse
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tracker import diagnostic_cli as cli, diagnostic_relations as relations
from tracker import diagnostic_worker as worker, requirement_diagnostics as detector
from tracker import monitoring, monitor_evidence, reward_detectors
from tracker.adapters import normalize
from tracker.schema import digest, dumps
from tracker.semantic_extraction import read, write
from tracker.store import Store
from test_diagnostic_monitors import source
from test_requirement_diagnostics import example, decide, transport


FIXTURE=Path(__file__).parent/'fixtures'/'diagnostic-harness-evidence.json'


def native(name):
    document=json.loads(FIXTURE.read_text(encoding='utf-8'))['cases'][name]['document']
    return normalize(document)[0]


def event(identifier,actor='agent',kind='action',trajectory='worker',context='before',**extra):
    return dict(id=identifier,actor=actor,kind=kind,text=identifier,
        trajectory_id=trajectory,context_id=context,**extra)


def scoped(rows):return source(task='See attributed instruction events in the trace.',trace=dumps(rows))


def negative(req):
    return {k:{'value':'task_requirement' if req['state']['stage']=='requirement_extraction' else 'none'}
            for k in req['questions']},digest(req)


def positive(req):
    answers,key=negative(req)
    if req['state']['stage']=='requirement_conflict_scan':
        for field,q in req['questions'].items():
            answers[field]['value']=next((cid for cid in q['criteria'] if cid in req['state']['source_fragments']),'none')
    return answers,key


def wire(req):
    answers,_=positive(req)
    return {'model':req['model'],'answers':{k:{'type':'choice','probabilities':{
        option:float(option==answers[k]['value']) for option in q['criteria']}} for k,q in req['questions'].items()}}


class RequirementHarnessTests(unittest.TestCase):
    def test_versions_one_two_five_retain_frozen_request_and_result_hashes(self):
        expected={
            detector.VERSION:('requirement-diagnostics-fb804f22381045bdc8d8','2d2630e1525f26eb677081fe976af5d71907c1d8f388c447318516f6ce3e3137','0484bc9a8d1078d1fa5adb91484d2a7fa61040c98a947da2128325fc0f20f693'),
            detector.PRIORITIZED_VERSION:('requirement-diagnostics-956d675d47a4c133ccf5','2d2630e1525f26eb677081fe976af5d71907c1d8f388c447318516f6ce3e3137','9cfb135e6ce2e490869db703e9a3e12247af2e240cf31e2aff7384aaa2bc5a1a'),
            detector.LITERAL_VERSION:('requirement-diagnostics-082e17fac1a4b885e347','25b653934c9853ab50962fdb53f1c217aba20ed391a1f6cd333ed39feb952636','1d654ccbeaa01c743d7fe72e443a18b60ef47849f642cbf9ed98b659ab6fa915')}
        for version,(protocol,request,result) in expected.items():
            with self.subTest(version=version),TemporaryDirectory() as folder:
                s=example()
                self.assertEqual(detector.protocol(version)['id'],protocol)
                self.assertEqual([digest(r) for r in detector.term_requests(s,version=version)],['9c6cc544334bd727cb2e443d0b060829917d0e59a7915231ba85efe0cbfe54ee'])
                self.assertEqual([digest(r) for r in detector.requests(s,version=version)],[request])
                self.assertEqual(digest(detector.build(s,decide,version=version)),result)
                saved=detector.execute(s,folder,transport,version=version)
                self.assertTrue(detector.audit(s,saved,folder)['exact_replay'])
                self.assertEqual(detector.execute(s,folder,lambda _:self.fail('Legacy request must replay')),saved)

    def test_interleaved_context_and_trajectory_never_share_selectable_candidates(self):
        rows=[event('before'),event('requirement','user','instruction'),event('other','user','instruction',trajectory='other'),
              event('same'),event('other-action',trajectory='other'),event('after-reset',context='after'),
              event('unknown-order',order_known=False),event('later-rule','user','instruction'),event('later-action')]
        s=scoped(rows);requests=list(detector.requests(s));choices={}
        for req in requests:
            self.assertLessEqual(len(dumps(req)),120000)
            for field,q in req['questions'].items():
                term=req['state']['requirements'][field]
                self.assertIn(json.dumps(term['display_text']),q['instructions'])
                ids={req['state']['source_fragments'][cid]['event_id'] for cid in q['criteria'] if cid in req['state']['source_fragments']}
                choices.setdefault(term['event_id'],set()).update(ids)
                self.assertTrue(all(f['native_scope']==term['native_scope'] for f in req['state']['source_fragments'].values()))
        self.assertEqual(choices,{'requirement':{'same','later-action'},'other':{'other-action'},'later-rule':{'later-action'}})
        for req in detector.term_requests(s):
            self.assertEqual(len({tuple(t['native_scope']) for t in req['state']['instruction_paragraphs'].values()}),1)

    def test_native_reset_definitions_and_reused_call_ids_stay_in_context(self):
        run=native('reset-reused-call');s=detector.source_from_run(run)
        self.assertEqual(s['provenance']['capture'],relations.HARNESS_VERSION)
        events={e['id']:e for e in run['events']};seen=set()
        for req in detector.requests(s):
            state=req['state'];context=json.loads(state['native_scope'][-1]);seen.add(context)
            for link in state['recorded_result_links']:
                self.assertEqual(events[link['action_event_id']]['context_id'],context)
                self.assertEqual(events[link['feedback_event_id']]['context_id'],context)
            text=dumps(state['recorded_encoding_definitions'])
            self.assertIn('Read the current record' if context=='before-reset' else 'Change the selected record',text)
            self.assertNotIn('Change the selected record' if context=='before-reset' else 'Read the current record',text)
        self.assertEqual(seen,{'before-reset','after-reset'})

    def test_private_copied_external_and_tool_feedback_never_become_tasks(self):
        s=detector.source_from_run(native('private-user-tool'))
        self.assertNotIn('PRIVATE_',dumps(list(detector.term_requests(s))))
        self.assertNotIn('PRIVATE_',dumps(list(detector.requests(s))))
        s=scoped([event('rule','user','instruction'),event('action'),
            event('tool-user','user','feedback'),event('late-user','user','message'),
            event('private','user','instruction',agent_visible=False),
            event('copied','user','instruction',copied_context=True),
            event('external','user','external_instruction'),event('final')])
        self.assertEqual([t['event_id'] for t in detector.criteria(s)],['rule'])
        visible=dumps(list(detector.term_requests(s)))+dumps(list(detector.requests(s)))
        for marker in ('"event_id":"private"','"event_id":"copied"','"event_id":"external"'):self.assertNotIn(marker,visible)

    def test_explicit_global_task_supports_raw_exports_and_each_native_context(self):
        s=source(task='Keep every original payload.',trace='[agent dispatch] CONFLICT discard every payload')
        reqs=list(detector.requests(s));self.assertTrue(reqs)
        self.assertEqual(detector.build(s,decide)['metrics'][detector.METRIC]['value'],1)
        self.assertEqual(detector.build(source(),negative)['metrics'][detector.METRIC]['value'],0)
        self.assertEqual(detector.build(source(task=''),negative)['metrics'][detector.METRIC]['value'],None)
        for req in reqs:
            self.assertEqual(req['state']['recorded_result_links'],[])
            self.assertTrue(all('record_id' not in f for f in req['state']['source_fragments'].values()))
        s=scoped([event('local-rule','user','instruction'),event('same'),event('other',context='after')])
        s['task']='Global declared requirement.'
        choices={}
        for req in detector.requests(s):
            for field,q in req['questions'].items():
                term=req['state']['requirements'][field]
                choices.setdefault(term.get('event_id','global'),set()).update(
                    req['state']['source_fragments'][cid]['event_id'] for cid in q['criteria'] if cid in req['state']['source_fragments'])
        self.assertEqual(choices,{'global':{'same','other'},'local-rule':{'same'}})
        private=scoped([event('private','agent','action',agent_visible=False)]);private['task']='Global task'
        self.assertEqual(list(detector.requests(private)),[])

    def test_environment_definitions_are_bounded_reference_not_requirements(self):
        s=detector.source_from_run(native('environment-encoding'))
        self.assertNotIn('Activate the facing object',dumps(list(detector.term_requests(s))))
        reqs=list(detector.requests(s));self.assertTrue(reqs)
        for req in reqs:
            self.assertIn('Activate the facing object',dumps(req['state']['recorded_encoding_definitions']))
            self.assertIn('Object is locked',dumps(req['state']['recorded_encoding_definitions']))
            self.assertLessEqual(len(dumps(req)),120000)
        self.assertEqual(detector.build(s,negative)['metrics'][detector.METRIC]['value'],0)
        run=native('environment-encoding')
        for e in run['events']:
            if e.get('tool_contract'):e['tool_contract']['definition']['description']='LARGE DEFINITION '*1500
        clipped=detector.source_from_run(run)
        result=detector.build(clipped,negative)
        self.assertIsNone(result['metrics'][detector.METRIC]['value'])
        self.assertTrue(result['coverage']['incomplete_requirement_ids'])
        self.assertEqual(detector.build(clipped,positive)['metrics'][detector.METRIC]['value'],1)
        run=native('environment-encoding')
        for e in run['events']:
            if e.get('observation_contract'):e['observation_contract']['definition']['description']='LARGE OBSERVATION '*1500
        observed=detector.source_from_run(run)
        self.assertIsNone(detector.build(observed,negative)['metrics'][detector.METRIC]['value'])
        self.assertEqual(detector.build(observed,positive)['metrics'][detector.METRIC]['value'],1)

    def test_unrelated_large_definition_does_not_poison_complete_comparison(self):
        run=native('reset-reused-call')
        for e in run['events']:
            if e.get('context_id')=='after-reset' and e.get('tool_contract'):
                e['tool_contract']['definition']['description']='Unrelated definition '*1000
        s=detector.source_from_run(run)
        def select_first(req):
            answers,key=negative(req)
            if req['state']['stage']=='requirement_extraction':
                for i,term in enumerate(req['state']['instruction_paragraphs'].values()):
                    if 'browser B' in term['text']:answers['term_'+str(i)]['value']='context'
            return answers,key
        result=detector.build(s,select_first)
        self.assertEqual(result['metrics'][detector.METRIC]['value'],0)
        self.assertEqual(result['coverage']['incomplete_encoding_event_ids'],[])

    def test_worker_resume_registration_and_inspection_use_new_capture(self):
        with TemporaryDirectory() as folder:
            root=Path(folder);store=Store(root/'db');run=native('private-user-tool');store.add([run])
            selector=worker.selection(run_ids=[run['id']]);s=detector.source_from_run(run)
            self.assertEqual(worker.inventory(store,selector,'requirements')[0]['_source'],s)
            first=worker.execute(store,root/'worker',wire,selector=selector,protocol_name='requirements',max_new_calls=1)
            self.assertEqual(first['coverage']['counts'],{'pending':1})
            done=worker.execute(store,root/'worker',wire,selector=selector,protocol_name='requirements',max_new_calls=20)
            self.assertEqual(done['coverage']['counts'],{'complete':1})
            self.assertEqual(done['protocol']['schema'],detector.CURRENT_VERSION)
            self.assertTrue(worker.audit(store,root/'worker')['runs'][0]['validation']['exact_replay'])
            reward_detectors.activate(store,{'checks':['requirement_conflict'],'observer':done['protocol']['id']});monitoring.sync(store)
            with store.connect() as c:value=c.execute('SELECT id FROM monitor_values').fetchone()[0]
            receipt=monitor_evidence.read(store,value)
            self.assertEqual(receipt['measurement']['value'],1)
            self.assertTrue(receipt['explanation']['diagnostic_excerpts'])
            self.assertNotIn('PRIVATE_',dumps(receipt['explanation']['diagnostic_excerpts']))

    def test_saved_worker_and_cli_keep_legacy_capture_and_new_cli_uses_current(self):
        parser=argparse.ArgumentParser();cli.configure(parser.add_subparsers())
        self.assertIsNone(parser.parse_args(['monitors','work','--run-id','r']).protocol)
        with TemporaryDirectory() as folder:
            root=Path(folder);store=Store(root/'db');run=native('private-user-tool');store.add([run])
            selector=worker.selection(run_ids=[run['id']]);legacy=root/'legacy'
            _,config,_=worker.initialize(store,legacy,selector,'requirements')
            config['protocol']=detector.protocol(detector.LITERAL_VERSION);write(legacy/'worker.json',config)
            result=worker.execute(store,legacy,wire,selector=selector,protocol_name='requirements',max_new_calls=30)
            self.assertEqual(result['coverage']['counts'],{'complete':1})
            self.assertTrue(worker.audit(store,legacy)['runs'][0]['validation']['exact_replay'])
            self.assertEqual(worker.inventory(store,selector,'requirements',detector.LITERAL_VERSION)[0]['_source'],worker.source_monitor.from_run(run))
            old=root/'old';s=detector.source_from_run(run,detector.LITERAL_VERSION)
            detector.execute(s,old,wire,version=detector.LITERAL_VERSION)
            args=SimpleNamespace(run_id=run['id'],input=None,protocol='requirements',directory=str(old),audit_only=False,prompt_key=False)
            with redirect_stdout(StringIO()),patch('tracker.jev.JevClient._post',side_effect=AssertionError('Legacy calls must be cached')):
                cli.execute(args,store);args.audit_only=True;cli.execute(args,store)
            self.assertEqual(detector.workspace_protocol(old)['schema'],detector.LITERAL_VERSION)
            args.directory=str(root/'new');args.audit_only=False
            with redirect_stdout(StringIO()),patch('tracker.jev.JevClient._post',side_effect=wire):cli.execute(args,store)
            self.assertEqual(read(root/'new/input.json'),detector.source_from_run(run))
            args.audit_only=True
            with redirect_stdout(StringIO()):cli.execute(args,store)


if __name__=='__main__':unittest.main()
