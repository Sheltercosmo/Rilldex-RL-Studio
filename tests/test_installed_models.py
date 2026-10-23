from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from rilldex import candidate, models
from tracker.store import Store
from tracker.schema import InputError
from tests.test_semantic_extraction import fixture, response


class InstalledModelTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.calls=[]
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*a):pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                owner.calls.append(body)
                packet=json.loads(body['messages'][1]['content'])
                if packet.get('stage')=='connection-check':value={'ok':True}
                else:
                    r=packet['request'];s=r['source'];e={'event_id':s['event_id'],'quote':s['text']}
                    if r.get('stage')=='content':
                        fields={k:{'status':'not_expressed'} for k in r['field_contract']}
                        fields['summary']={'status':'expressed','text':s['text'],'evidence':[e]}
                        value={'citation_format':'source-quotes/1','candidates':[{'fields':fields}]}
                        if r.get('activity')=='plan':
                            value['candidates'][0]['plan_structure']={'schema':'local-plan-content/1','organization':'staged',
                                'steps':[{'id':'draft','text':'Write the Markdown report.','target':'Report content','evidence':[e]},
                                         {'id':'convert','text':'Convert to PDF.','target':'PDF report','evidence':[e]}],
                                'links':[{'from':'draft','to':'convert','kind':'precedes','evidence':[e]}],
                                'completion_criterion':{'status':'not_expressed'}}
                    elif r.get('stage')=='activity_readings':
                        value={'readings':[{'activity':'plan' if s['text'].startswith('First write') else 'inspect' if s['text'].startswith('Inspect item') else 'orient','text':s['text'],'evidence':[e]}]}
                    else:
                        value={'partitions':[{'units':[{'quote':s['text']}],'contributions':['Identifies the immediate correction.'],'rationale':'One contribution.'}]}
                raw=json.dumps({'choices':[{'message':{'content':json.dumps(value)}}]}).encode()
                self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)
        env={'RILLDEX_LLM_URL':f'http://127.0.0.1:{self.server.server_port}/v1/chat/completions',
             'RILLDEX_LLM_MODEL':'contract-fixture-v1','RILLDEX_LLM_PRESET':'custom','NO_PROXY':'127.0.0.1,localhost'}
        self.env=patch.dict(os.environ,env);self.env.start();self.addCleanup(self.env.stop)

    def test_configuration_is_offline_and_probe_is_exactly_one_request(self):
        self.assertEqual(models.check()['candidate']['state'],'configured')
        self.assertEqual(len(self.calls),0)
        self.assertEqual(models.probe()['requests'],1)
        self.assertEqual(len(self.calls),1)
        self.assertEqual(candidate.settings({'RILLDEX_LLM_PRESET':'ollama','RILLDEX_LLM_MODEL':'pinned'})['endpoint'],'http://127.0.0.1:11434/v1/chat/completions')
        self.assertNotIn('key',models.check()['candidate'])

    def test_installed_module_subprocess_uses_http_contract(self):
        p=subprocess.run([sys.executable,'-m','rilldex.candidate'],input=json.dumps({'stage':'connection-check'}),
                         text=True,capture_output=True,timeout=20)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(json.loads(p.stdout),{'ok':True})

    def test_pilot_lifetime_budget_resume_and_model_identity(self):
        store=Store(self.root/'study.sqlite');run=fixture()
        run['events']=[e for e in run['events'] if e['actor']=='agent']
        store.add([run]);directory=self.root/'pilot'
        first=models.pilot(store,directory,run['id'],candidate_calls=1,decision_calls=1,input_bytes=1000000,transport=response)
        self.assertEqual(first['status'],'budget_reached')
        calls=len(self.calls)
        second=models.pilot(store,directory,run['id'],candidate_calls=1,decision_calls=1,input_bytes=1000000,transport=response)
        self.assertEqual(len(self.calls),calls)
        self.assertEqual(second['status'],'budget_reached')
        final=models.pilot(store,directory,run['id'],candidate_calls=20,decision_calls=20,input_bytes=1000000,transport=response)
        self.assertEqual(final['status'],'complete_local_extraction')
        self.assertIn('observer=',final['map_url'])
        from tracker.first_session import readiness
        available=next(f for f in readiness(store,run_ids=[run['id']])['features'] if f['id']=='semantic')
        self.assertEqual(available['state'],'available')
        self.assertTrue(available['url'].startswith('/semantic-map?'))
        calls=len(self.calls)
        models.pilot(store,directory,run['id'],candidate_calls=20,decision_calls=20,input_bytes=1000000,transport=lambda _:self.fail('Must use cache'))
        self.assertEqual(len(self.calls),calls)
        with patch.dict(os.environ,{'RILLDEX_LLM_MODEL':'changed'}):
            with self.assertRaisesRegex(InputError,'Model configuration changed'):
                models.pilot(store,directory,run['id'])

    def test_managed_pilot_checks_before_calls_and_restores_saved_progress(self):
        from tracker.model_pilot import ModelPilotService
        store=Store(self.root/'managed.sqlite');run=fixture();store.add([run])
        service=ModelPilotService(store)
        body=dict(run_id=run['id'],candidate_calls=0,decision_calls=0,input_bytes=0)
        with self.assertRaises(InputError):service.start({**body,'candidate_calls':True})
        service.start(body)
        service.thread.join(10)
        self.assertFalse(service.thread.is_alive())
        self.assertEqual(len(self.calls),0)
        state=service.status()['pilot'];self.assertEqual(state['state'],'budget_reached')
        restored=ModelPilotService(store).status()['pilot']
        self.assertEqual(restored['directory'],state['directory'])
        self.assertEqual(restored['state'],state['state'])

    def test_work_links_share_lifetime_budget_and_leave_local_map_available(self):
        from tests.test_action_scope_pages import fixture as action_fixture,transport as pair_transport
        from tracker.semantic_extraction import read
        from tracker.semantic_catalog import load
        store=Store(self.root/'links.sqlite');run=action_fixture(3);store.add([run]);directory=self.root/'links'
        def decide(req):
            if req['state']['stage']=='action_target_scope_pairs':return pair_transport(req)
            if req['state']['stage']=='method_comparison':
                from tests.test_method_comparison import native_response
                return native_response(req,work='different_work')
            if req['state']['stage']=='executor_reports':
                from tests.test_execution_reports import answer
                return answer(req,'not_reported')
            if req['state']['stage']=='activity':
                return {'model':req['model'],'answers':{'choice':{'type':'choice',
                    'probabilities':{c:float(c=='inspect') for c in req['questions']['choice']['criteria']}}}}
            return response(req)
        # Three native actions take two local choices each, then two work pages.
        initial=models.pilot(store,directory,run['id'],candidate_calls=20,decision_calls=7,input_bytes=1000000,transport=decide)
        self.assertEqual(initial['status'],'budget_reached',initial)
        self.assertEqual(initial['map_scope'],'local_activities')
        self.assertEqual(initial['layers']['action_targets']['coverage']['compared_pairs'],1)
        calls=len(self.calls)
        resumed=models.pilot(store,directory,run['id'],candidate_calls=20,decision_calls=13,input_bytes=1000000,transport=decide)
        self.assertEqual(resumed['status'],'complete_local_extraction',resumed)
        self.assertEqual(resumed['map_scope'],'activities_and_work_links')
        self.assertEqual(resumed['layers']['action_targets']['coverage']['compared_pairs'],3)
        self.assertEqual(len(self.calls),calls)
        self.assertEqual(resumed['provider_usage']['providers']['jev']['attempts'],13)
        self.assertEqual(resumed['last_execution']['cached_decisions_this_execution'],7)
        # The originally published local observer remains loadable after links arrive.
        from urllib.parse import parse_qs,urlsplit
        observer=parse_qs(urlsplit(initial['map_url']).query)['observer'][0]
        self.assertTrue(load(run,observer,store)['available'])
        models.pilot(store,directory,run['id'],candidate_calls=20,decision_calls=13,input_bytes=1000000,
                     transport=lambda _:self.fail('Cached pages should not be called'))

    def test_old_pilot_identity_remains_local_only(self):
        from tracker.semantic_extraction import write
        from tracker.jev import DEFAULT_MODEL
        store=Store(self.root/'old.sqlite');run=fixture();run['events']=[e for e in run['events'] if e['actor']=='agent'];store.add([run])
        directory=self.root/'old';config=candidate.settings()
        write(directory/'model.json',dict(adapter=candidate.VERSION,endpoint=config['endpoint'],model=config['model'],decision_model=DEFAULT_MODEL))
        result=models.pilot(store,directory,run['id'],candidate_calls=20,decision_calls=20,input_bytes=1000000,transport=response)
        self.assertEqual(result['layers']['action_targets']['status'],'not_requested')
        self.assertNotIn('action_target_version',result['model'])
        self.assertEqual(result['layers']['plan_relations']['status'],'not_requested')
        self.assertEqual(result['layers']['execution_reports']['status'],'not_requested')
        self.assertEqual(result['layers']['method_comparison']['status'],'not_requested')

    def test_plan_layer_resume_publishes_plan_map_and_preserves_local_observer(self):
        from tests.test_plan_scope_pages import fixture as plan_fixture,transport as plan_transport
        from tests.test_action_scope_pages import transport as pair_transport
        from tracker.semantic_extraction import read
        from tracker.semantic_catalog import load
        from urllib.parse import parse_qs,urlsplit
        store=Store(self.root/'plans.sqlite');run=plan_fixture();store.add([run]);directory=self.root/'plans'
        seen=[]
        def decide(req):
            seen.append(req['state']['stage'])
            if req['state']['stage']=='method_comparison':
                from tests.test_method_comparison import native_response
                return native_response(req,work='different_work')
            if req['state']['stage']=='action_target_scope_pairs':return pair_transport(req)
            if req['state']['stage']=='executor_reports':
                from tests.test_execution_reports import answer
                return answer(req,'not_reported')
            return plan_transport(req)
        full=models.pilot(store,self.root/'baseline',run['id'],candidate_calls=100,decision_calls=100,input_bytes=5000000,transport=decide)
        self.assertEqual(full['status'],'complete_local_extraction',full)
        local_calls=next(i for i,s in enumerate(seen) if s=='plan_stage_roles');total=len(seen)
        initial=models.pilot(store,directory,run['id'],candidate_calls=100,decision_calls=local_calls+1,input_bytes=5000000,transport=decide)
        self.assertEqual(initial['status'],'budget_reached',initial)
        self.assertFalse(initial['plan_map_available'])
        self.assertEqual(initial['layers']['plan_relations']['coverage']['compared_pairs'],2)
        self.assertEqual(initial['layers']['plan_relations']['coverage']['pending_pairs'],6)
        calls=len(self.calls)
        result=models.pilot(store,directory,run['id'],candidate_calls=100,decision_calls=total,input_bytes=5000000,transport=decide)
        self.assertEqual(result['status'],'complete_local_extraction',result)
        self.assertTrue(result['plan_map_available'])
        self.assertIn('level=plans',result['map_url'])
        self.assertEqual(len(self.calls),calls)
        self.assertEqual(result['provider_usage']['providers']['jev']['attempts'],total)
        old=parse_qs(urlsplit(initial['map_url']).query)['observer'][0]
        new=parse_qs(urlsplit(result['map_url']).query)['observer'][0]
        self.assertTrue(load(run,old,store)['available'])
        self.assertFalse(any(r.get('plan_step_id') for r in load(run,old,store)['document']['relations']))
        mapped=load(run,new,store)['document']
        self.assertEqual(len([r for r in mapped['relations'] if r.get('plan_step_id')]),4)
        models.pilot(store,directory,run['id'],candidate_calls=100,decision_calls=total,input_bytes=5000000,
                     transport=lambda _:self.fail('Completed plan pilot must replay cached decisions'))

    def test_managed_pilot_publishes_map_and_reuses_completed_work(self):
        from tracker.model_pilot import ModelPilotService
        store=Store(self.root/'managed-complete.sqlite');run=fixture()
        run['events']=[e for e in run['events'] if e['actor']=='agent'];store.add([run])
        service=ModelPilotService(store)
        body=dict(run_id=run['id'],candidate_calls=20,decision_calls=20,input_bytes=1000000)
        with patch.dict(os.environ,{'JEV_API_KEY':'contract-test-only'}),patch('tracker.jev.JevClient') as client:
            client.return_value.transport.side_effect=response
            service.start(body);service.thread.join(15)
            self.assertFalse(service.thread.is_alive())
            state=service.status()['pilot']
            self.assertEqual(state['state'],'complete_local_extraction',state)
            self.assertIn('observer=',state['result']['map_url'])
            calls=len(self.calls)
            service.start(body);service.thread.join(15)
            self.assertEqual(len(self.calls),calls)

    @unittest.skipUnless(os.environ.get('RILLDEX_INSTALLED_PYTHON'),'Set RILLDEX_INSTALLED_PYTHON to check a fresh wheel outside the checkout')
    def test_fresh_wheel_pilot_outside_checkout(self):
        run=fixture();run['events']=[e for e in run['events'] if e['actor']=='agent']
        (self.root/'run.json').write_text(json.dumps(run),encoding='utf-8')
        script='''import json
from pathlib import Path
from tracker.store import Store
from rilldex.models import pilot
from tracker.jev import DEFAULT_MODEL
def transport(req):
 stage=req['state']['stage']; chosen='p0' if stage=='partition' else 'orient' if stage=='activity' else 'c0'
 options=list(req['questions']['choice']['criteria'])
 return {'model':DEFAULT_MODEL,'answers':{'choice':{'type':'choice','probabilities':{k:1.0 if k==chosen else 0.0 for k in options}}}}
store=Store('installed.sqlite');run=json.loads(Path('run.json').read_text(encoding='utf-8'));store.add([run])
result=pilot(store,'pilot',run['id'],candidate_calls=20,decision_calls=20,input_bytes=1000000,transport=transport)
assert result['status']=='complete_local_extraction',result
again=pilot(store,'pilot',run['id'],candidate_calls=20,decision_calls=20,input_bytes=1000000,transport=lambda _: (_ for _ in ()).throw(AssertionError('cache missed')))
assert again['last_execution']['candidate_calls_this_execution']==0
print(json.dumps({'map':result['map_url'],'calls':result['last_execution']['candidate_calls_this_execution']}))
'''
        env={k:v for k,v in os.environ.items() if k!='PYTHONPATH'}
        p=subprocess.run([os.environ['RILLDEX_INSTALLED_PYTHON'],'-c',script],cwd=self.root,env=env,
                         text=True,capture_output=True,timeout=40)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(json.loads(p.stdout)['calls'],len(self.calls))
        self.assertGreater(len(self.calls),0)


if __name__=='__main__':unittest.main()
