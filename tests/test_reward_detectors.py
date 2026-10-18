import json
from pathlib import Path
import shutil
import subprocess
import unittest
from urllib.request import Request, urlopen

from tracker import graph_store, monitoring, reward_detectors as detectors
from tracker.adapters import normalize
from tracker.schema import InputError
from tracker.workspace_analysis import Workspace
from test_tracker import harbor
import test_generation_cohort_transport as transport
import test_diagnostic_monitors as diagnostic_tests


class RewardDetectorTests(unittest.TestCase):
    setUp=transport.GenerationCohortTransportTests.setUp
    start_server=transport.GenerationCohortTransportTests.start_server
    stop_server=staticmethod(transport.GenerationCohortTransportTests.stop_server)

    def ingest(self,document,revision=0,state='complete',name='late'):
        return self.store.ingest(dict(producer='trainer',rollout_id=name,revision=revision,state=state,
            format='harbor',document=document,metadata={'experiment':'train','training_step':1,'reward_definition':'delivery/v3'}))['id']

    def add(self,name,reward=1,passed=False,definition='delivery/v3',complete=True):
        run=normalize(harbor(),'harbor',{'experiment':'train','training_step':1,'reward_definition':definition})[0]
        run['id']='run-'+name
        run['raw']['check']={'passed':passed}
        run['raw']['components']={'completion':reward,'constraint':passed}
        run['outcome']['recorded_reward']=reward
        if not complete:run['raw']['check'].pop('passed')
        self.store.add([run])
        with self.store.connect() as c:graph_store.save(c,graph_store.build(run))
        return run

    def detector(self,**changes):
        settings=dict(version='1',description='Reward-positive rollouts with a failed recorded check.',
            reward_definition='delivery/v3',stage='reward_disagreement',
            inputs={'reward':'/outcome/recorded_reward','passed':'/raw/check/passed'})
        settings.update(changes)
        return Workspace(self.db,experiment='train',observer='source').reward_detector('Delivery check',**settings)

    @staticmethod
    def check(ctx):
        if ctx.inputs['reward']<=0:return {'status':'not_applicable','summary':'Outside comparison range'}
        return {'status':'clear' if ctx.inputs['passed'] else 'flagged','summary':'Compared recorded check',
                'input_evidence':['reward','passed']}

    def rows(self,monitor):
        return {r['run']['id']:r['measurement'] for r in monitoring.cases(self.store,monitor.id)['rows']}

    def test_backfill_denominators_false_zero_missing_and_reward_versions(self):
        for name,reward,passed,definition,complete in [
            ('bad',1,False,'delivery/v3',True),('good',1,True,'delivery/v3',True),
            ('zero',0,False,'delivery/v3',True),('missing',1,False,'delivery/v3',False),
            ('different',1,False,'delivery/v4',True),('unversioned',1,False,None,True)]:
            self.add(name,reward,passed,definition,complete)
        monitor=self.detector();seen=[]
        def check(ctx):seen.append(ctx.run['id']);return self.check(ctx)
        self.assertEqual(monitor.run(check)['published'],6)
        self.assertEqual(set(seen),{'run-bad','run-good','run-zero'})
        rows=self.rows(monitor)
        self.assertEqual(rows['run-bad']['value'],1);self.assertEqual(rows['run-good']['value'],0)
        for name in ['zero','missing','different','unversioned']:self.assertIsNone(rows['run-'+name]['value'])
        self.assertEqual(rows['run-zero']['details']['detector']['status'],'not_applicable')
        self.assertEqual(rows['run-missing']['unknown'],1)
        self.assertEqual(rows['run-bad']['details']['detector']['input_evidence']['passed']['value'],False)
        self.assertEqual(rows['run-bad']['feedback']['severity'],'warning')

    def test_restart_late_source_revision_dependencies_and_pause(self):
        document=harbor();document['score']=1;document['check']={}
        self.ingest(document,state='in_progress')
        settings={'inputs':{'reward':'/raw/score','passed':'/raw/check/passed'}}
        monitor=self.detector(**settings)
        self.assertEqual(monitor.run(lambda _:self.fail('Incomplete capture'))['waiting'],1)
        old=self.ingest(document,1)
        self.assertEqual(monitor.run(self.check)['published'],1)
        self.assertEqual(monitor.run(lambda _:self.fail('Repeated callback'))['skipped'],1)
        document['check']['passed']=False
        current=self.ingest(document,2)
        self.assertEqual(monitor.run(self.check)['published'],1)
        self.assertEqual(self.rows(monitor)[current]['value'],1)
        self.assertNotIn(old,self.rows(monitor))
        with self.store.connect() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM custom_monitor_inputs WHERE monitor_id=?',(monitor.id,)).fetchone()[0],2)
        self.assertEqual(monitor.run(self.check,dependencies={'external_check':'v2'})['published'],1)
        monitoring.enabled(self.store,monitor.id,False)
        self.assertTrue(self.detector(**settings).run(lambda _:self.fail('Paused callback'))['paused'])
        self.assertNotEqual(self.detector(config={'new_rule':True}).id,monitor.id)

    @unittest.skipUnless(shutil.which('node'),'Node is needed to execute the UI-generated Python template')
    def test_generated_python_runs_against_real_ingestion_and_shared_monitoring(self):
        cases=[('flagged',-2,False,'artifact-v1'),('clear',-2,True,'artifact-v1'),
               ('not_applicable',-1,False,'artifact-v1'),('unknown',-2,False,'old-artifact'),
               ('invalid_boolean',-2,0,'artifact-v1')]
        ids={}
        for name,score,passed,subject in cases:
            document=harbor();document.update(score=score,subject='artifact-v1',check={
                'passed':passed,'subject_id':subject,'reward_definition':'delivery/v3'})
            ids[name]=self.ingest(document,name=name)
        options=dict(template='reward',database=str(self.db),experiment='train',rewardDefinition='delivery/v3',
            rewardPath='/raw/score',checkPath='/raw/check',subjectPath='/raw/subject',threshold=-2,direction='le')
        code=subprocess.run([shutil.which('node'),'-e',
            "const {script}=require('./tracker/web/custom-monitor-setup.js');process.stdout.write(script(JSON.parse(require('node:fs').readFileSync(0,'utf8'))));"],
            input=json.dumps(options),text=True,encoding='utf-8',capture_output=True,check=True,
            cwd=Path(__file__).resolve().parents[1]).stdout
        namespace={'__name__':'generated_test'};exec(compile(code,'generated_reward_detector.py','exec'),namespace)
        monitor=namespace['monitor'];detect=namespace['detect']
        self.assertEqual(monitor.run(detect)['published'],5)
        rows=self.rows(monitor)
        for status in ['flagged','clear','not_applicable','unknown']:
            self.assertEqual(rows[ids[status]]['details']['detector']['status'],status)
        self.assertEqual(rows[ids['invalid_boolean']]['details']['detector']['status'],'unknown')
        self.assertEqual(monitor.run(lambda _:self.fail('Template cache not reused'))['skipped'],5)
        snapshot=next(m for m in monitoring.snapshot(self.store)['monitors'] if m['id']==monitor.id)
        self.assertEqual(snapshot['coverage']['available'],2)
        self.assertEqual(snapshot['detector_counts'],{'flagged':1,'clear':1,'unknown':2,'not_applicable':1})
        self.assertEqual(snapshot['series'][0]['bins'][0]['value'],.5)

    def test_long_trace_inputs_can_cite_graph_nodes_without_copying_full_text(self):
        document=harbor();document['long_trace']='a'*200000
        rid=self.ingest(document)
        monitor=self.detector(inputs={'trace':'/raw/long_trace'})
        def check(ctx):
            self.assertEqual(len(ctx.inputs['trace']),200000)
            return {'status':'flagged','summary':'Test fixture finding',
                    'evidence_ids':[ctx.graph['nodes'][0]['id']]}
        self.assertEqual(monitor.run(check)['errors'],0)
        self.assertEqual(self.rows(monitor)[rid]['value'],1)

    def test_negative_and_multicomponent_rewards_use_custom_logic_without_rescaling(self):
        self.add('a',-2,False)
        monitor=self.detector(inputs={'components':'/raw/components'})
        def check(ctx):
            self.assertEqual(ctx.inputs['components'],{'completion':-2,'constraint':False})
            return {'status':'flagged','summary':'Penalty and constraint discrepancy','input_evidence':['components']}
        self.assertEqual(monitor.run(check)['published'],1)
        self.assertEqual(self.rows(monitor)['run-a']['value'],1)

    def test_invalid_findings_are_errors_not_clean_samples_and_evidence_is_frozen(self):
        self.add('a');self.add('b');monitor=self.detector()
        def check(ctx):
            if ctx.run['id']=='run-a':return {'status':'flagged','summary':'No witness'}
            ctx.inputs['passed']=True
            return {'status':'flagged','summary':'Witness retained','input_evidence':['passed']}
        self.assertEqual(monitor.run(check)['errors'],1)
        rows=self.rows(monitor);self.assertEqual(rows['run-a']['status'],'error')
        self.assertIsNone(rows['run-a']['value'])
        self.assertFalse(rows['run-b']['details']['detector']['input_evidence']['passed']['value'])
        ws=Workspace(self.db)
        values=ws.sql('SELECT value, feedback_summary FROM monitor_values WHERE monitor_id = ?', [monitor.id]).rows
        self.assertEqual(len(values),2)

    def test_strict_paths_and_contracts_before_registration(self):
        self.assertEqual(detectors.lookup({'a/b':{'~x':[0,False]}},'/a~1b/~0x/1'),False)
        self.assertIs(detectors.lookup({'x':[1]},'/x/01'),detectors.MISSING)
        for change in [{'inputs':{}},{'inputs':{'bad key':'/x'}},{'inputs':{'x':'not/pointer'}},
                       {'inputs':{'x':'/a~2b'}},{'stage':'confirmed_hacking'},{'config':[]},{'reward_definition':''}]:
            with self.assertRaises(InputError):self.detector(**change)
        self.assertEqual(monitoring.definitions(self.store),[])

    def test_http_catalog_batch_selection_and_custom_values_share_registry(self):
        run=self.add('a');monitor=self.detector();monitor.run(self.check)
        endpoint=self.start_server()
        with urlopen(endpoint+'/api/monitoring/options') as response:options=json.load(response)
        self.assertEqual(len(options['reward_checks']['checks']),10)
        self.assertTrue(any(c['id']=='requirement_conflict' for c in options['reward_checks']['checks']))
        with urlopen(endpoint+'/reward-checks.js') as response:self.assertIn(b'RewardChecks',response.read())
        body={'checks':['reward_diagnostic_failure_observed','reward_aggregation_gap'],'population':{'experiment':'train'}}
        def post():
            with urlopen(Request(endpoint+'/api/monitoring/reward-checks',data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})) as response:return json.load(response)
        added=post();self.assertEqual(len(added['added']),2)
        monitoring.enabled(self.store,added['added'][0],False)
        self.assertEqual(len(post()['existing']),2)
        self.assertFalse(next(m for m in monitoring.definitions(self.store) if m['id']==added['added'][0])['enabled'])
        before=monitoring.definitions(self.store)
        with self.assertRaises(InputError):detectors.activate(self.store,{'checks':['reward_aggregation_gap','evaluator_bypass']})
        self.assertEqual(monitoring.definitions(self.store),before)

    def test_saved_diagnostic_checks_are_selected_without_new_inference(self):
        from tracker import diagnostic_monitors as diagnostics
        run=self.add('diagnostics');source=diagnostics.from_run(run)
        directory=self.root/'mock-diagnostics'
        result=diagnostics.execute(source,directory,diagnostic_tests.transport)
        saved=diagnostics.register(self.store,run,source,result,directory)
        observer=saved['observer']
        catalog=detectors.catalog(self.store)
        self.assertIn(observer,[row['id'] for row in catalog['observers']])
        displayed=next(row for row in catalog['observers'] if row['id']==observer)
        self.assertEqual(displayed['protocol_version'],diagnostics.VERSION)
        self.assertEqual(displayed['checks']['evaluator_bypass']['description'],diagnostics.DETECTORS['evaluator_bypass'][1])
        added=detectors.activate(self.store,{'checks':list(diagnostics.DETECTORS),'observer':observer})
        self.assertEqual(len(added['added']),6)
        monitoring.sync(self.store)
        for identifier in added['added']:
            rows=monitoring.cases(self.store,identifier)['rows']
            self.assertEqual(rows[0]['measurement']['value'],0)

    def test_other_custom_monitor_config_is_not_interpreted_as_detector(self):
        self.add('a')
        monitor=Workspace(self.db).monitor('Generic',version='1',description='Unrelated code monitor',
            config={'reward_detector':'application-specific text'})
        monitor.run(lambda _: {'value':2})
        row=next(m for m in monitoring.snapshot(self.store)['monitors'] if m['id']==monitor.id)
        self.assertNotIn('detector_counts',row)
