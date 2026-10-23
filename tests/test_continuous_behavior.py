"""Installed candidate HTTP and authored decisions; not model-accuracy tests."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

from rilldex import models
from tracker import semantic_watch as worker,semantic_catalog,monitoring
from tracker.adapters import normalize
from tracker.schema import InputError,digest
from tracker.semantic_extraction import read,write
from tracker.store import Store
from tests import test_installed_models as installed
from tests.test_pilot_execution_reports import fixture,transport


def source(name='first',step=1):
    run=fixture();run['metadata'].update(experiment='training',task_id=name,training_step=step,training_step_basis='learner_update')
    for event in run['events']:
        event['text']=event['text'].replace('report.md',name+'.md').replace('report.pdf',name+'.pdf')+' ['+name+']'
    run['id']=digest(run)[:24]
    return run


class ContinuousBehaviorTests(unittest.TestCase):
    setUp=installed.InstalledModelTests.setUp

    def begin(self):
        self.store=Store(self.root/'study.sqlite');self.run=source();self.store.add([self.run]);self.pilot=self.root/'pilot'
        return models.pilot(self.store,self.pilot,self.run['id'],candidate_calls=100,decision_calls=100,input_bytes=5000000,transport=transport)

    def observe(self,**kwargs):
        return models.watch(self.store,self.root/'watch',experiment='training',from_pilot=self.pilot,**kwargs)

    def test_pilot_reuse_new_arrival_partial_resume_metrics_and_frozen_archive(self):
        baseline=self.begin();calls=len(self.calls)
        first=self.observe(transport=lambda _:self.fail('Pilot must reuse exact selections at zero allowance'))
        observer=first['observer'];self.assertEqual(first['used'],worker.ZERO);self.assertEqual(len(self.calls),calls)
        self.assertEqual(first['current_published'],1)
        saved=semantic_catalog.load(self.run,observer,self.store)
        self.assertEqual(len(saved['document']['execution_returns']),1)
        self.assertEqual(saved['document']['provenance']['relation_harness'],worker.behavior_options()['plan_relation_version'])
        self.assertEqual(len(first['monitors']),7)
        self.assertTrue(any(m.get('analysis',{}).get('measure')=='error_report_repeat_fraction' for m in monitoring.definitions(self.store)))
        second=source('later',2);self.store.add([second])
        self.store=Store(self.store.path)
        # Stop inside feedback, after activities and all relation pages finish.
        cap=baseline['provider_usage']['providers']['jev']['attempts']-4
        partial=self.observe(candidate_calls=100,decision_calls=cap,input_bytes=5000000,transport=transport)
        row=next(j for j in partial['jobs'] if j['run_id']==second['id'])
        self.assertEqual(row['status'],'budget_reached',row)
        self.assertEqual(row['details']['layers']['execution_reports']['coverage']['pending_pairs'],2)
        with self.store.connect() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM observer_archives WHERE observer=?',(observer,)).fetchone()[0],1)
        self.assertEqual(self.observe(transport=lambda _:self.fail('Polling cannot refill budget'))['used'],partial['used'])
        calls=len(self.calls);seen=[]
        def rest(req):seen.append(req['state']['stage']);return transport(req)
        resumed=self.observe(decision_calls=cap+4,transport=rest,retry_runs=[second['id']])
        self.assertEqual(seen,['executor_reports','executor_reports','method_comparison','method_comparison']);self.assertEqual(len(self.calls),calls)
        self.assertEqual(resumed['current_published'],2);self.assertEqual(resumed['observer'],observer)
        self.assertEqual(semantic_catalog.load(self.run,observer,self.store),saved)
        with self.store.connect() as c:
            values=[json.loads(r[0]) for r in c.execute('SELECT v.document FROM monitor_values v JOIN monitor_latest l ON l.value_id=v.id WHERE v.monitor_id=?',(first['monitors'][0],))]
        self.assertEqual(len(values),2)
        self.assertTrue(all(v['value']==0.2 for v in values),values)
        monitoring.enabled(self.store,first['monitors'][0],False)
        monitoring.enabled(self.store,first['monitors'][-1],False)
        repeated=self.observe(transport=lambda _:self.fail('Completed collection must not call'))
        self.assertEqual(repeated['used'],resumed['used'])
        self.assertFalse(next(m for m in monitoring.definitions(self.store) if m['id']==first['monitors'][0])['enabled'])
        self.assertFalse(next(m for m in monitoring.definitions(self.store) if m['id']==first['monitors'][-1])['enabled'])
        for identifier in first['monitors'][-2:]:
            values=monitoring.values(self.store,identifier,[self.run['id'],second['id']])
            self.assertEqual(len(values),2)
            self.assertTrue(all(v['denominator']==1 and v['unknown']==0 for v in values.values()),values)
        self.assertIn('view=measures',repeated['dashboard_url'])

    def test_new_worker_protocol_identity_and_explicit_limits(self):
        self.store=Store(self.root/'fresh.sqlite');run=source();self.store.add([run])
        first=models.watch(self.store,self.root/'fresh',experiment='training',transport=transport)
        self.assertEqual(first['used'],worker.ZERO)
        self.assertEqual(first['workspace_options'],worker.behavior_options())
        self.assertEqual(first['job_counts'],{'budget_reached':1})
        with patch.dict(os.environ,{'RILLDEX_LLM_MODEL':'different'}):
            with self.assertRaisesRegex(InputError,'protocol changed'):
                models.watch(self.store,self.root/'fresh',experiment='training',transport=transport)
        done=models.watch(self.store,self.root/'fresh',experiment='training',transport=transport,
            candidate_calls=100,decision_calls=100,input_bytes=5000000,retry_runs=[run['id']])
        self.assertEqual(done['current_published'],1)
        with self.assertRaisesRegex(InputError,'only increase'):
            models.watch(self.store,self.root/'fresh',experiment='training',decision_calls=0,transport=transport)

    def test_promotion_checks_candidate_identity_before_any_calls(self):
        self.begin();count=len(self.calls)
        with patch.dict(os.environ,{'RILLDEX_LLM_MODEL':'different'}):
            with self.assertRaisesRegex(InputError,'Pilot model configuration differs'):
                self.observe(transport=lambda _:self.fail('No provider calls'))
        self.assertEqual(len(self.calls),count)
        self.assertFalse((self.root/'watch/watch.json').exists())

    def test_worker_flags_pin_relationship_versions_without_calls(self):
        store=Store(self.root/'cli.sqlite')
        args=[sys.executable,'-m','rilldex','--db',str(store.path),'semantic','watch-init',str(self.root/'configured'),
            '--experiment','training','--label','Training behavior','--behavior-links']
        process=subprocess.run(args,capture_output=True,text=True,timeout=20)
        self.assertEqual(process.returncode,0,process.stderr)
        result=json.loads(process.stdout)
        self.assertEqual(result['workspace_options'],worker.behavior_options())
        self.assertEqual(result['used'],worker.ZERO)

    def test_growing_relationship_maps_never_become_completed_rollout_rates(self):
        from copy import deepcopy
        store=Store(self.root/'prefix.sqlite');raw=fixture()['raw'];prefix=deepcopy(raw)
        prefix['trajectory']=prefix['trajectory'][:3]
        metadata=dict(experiment='prefix-training',training_step=1,training_step_basis='learner_update')
        def ingest(document,revision,state):
            return store.ingest(dict(producer='agent',rollout_id='one',revision=revision,state=state,
                                     document=document,metadata=metadata))['id']
        first_id=ingest(prefix,0,'in_progress');directory=self.root/'prefix-worker'
        first=models.watch(store,directory,experiment='prefix-training',live_prefixes=True,
            candidate_calls=100,decision_calls=100,input_bytes=10000000,transport=transport)
        self.assertEqual(first['current_published'],1)
        first_run=store.get(first_id,raw=True)['run']
        original=semantic_catalog.load(first_run,first['observer'],store)
        self.assertEqual(first['jobs'][0]['details']['source_complete_at_publication'],False)
        with store.connect() as c:
            values=[json.loads(r[0]) for r in c.execute('SELECT v.document FROM monitor_values v JOIN monitor_latest l ON l.value_id=v.id WHERE v.run_id=?',(first_id,))]
        self.assertEqual(len(values),7)
        self.assertTrue(all(v['status']=='incomplete' and v['value'] is None for v in values))
        final_id=ingest(raw,1,'complete');seen=[]
        def observe(req):seen.append(req['state']['stage']);return transport(req)
        final=models.watch(store,directory,experiment='prefix-training',live_prefixes=True,transport=observe)
        self.assertEqual(final['current_published'],1)
        row=next(j for j in final['jobs'] if j['run_id']==final_id)
        self.assertTrue(row['details']['source_complete_at_publication'])
        mapped=semantic_catalog.load(store.get(final_id,raw=True)['run'],final['observer'],store)
        self.assertEqual(len(mapped['document']['execution_returns']),1)
        self.assertEqual(semantic_catalog.load(first_run,first['observer'],store),original)
        receipt=read(directory/'runs'/final_id/'last-execution.json')
        self.assertGreater(receipt['exact_reused_decisions'],0)
        with store.connect() as c:
            values=[json.loads(r[0]) for r in c.execute('SELECT v.document FROM monitor_values v JOIN monitor_latest l ON l.value_id=v.id WHERE v.run_id=?',(final_id,))]
        self.assertTrue(all(v['status']=='available' for v in values),values)

    def test_missing_relation_file_cannot_publish_from_completed_progress_alone(self):
        from tracker.plan_relations import path_for
        self.begin();observed=self.observe();identifier,definition,_=worker.load(self.store,self.root/'watch')
        root=self.root/'watch/runs'/self.run['id'];extraction=read(root/'results'/f"{self.run['id']}.json")
        path_for(root,extraction,worker.behavior_options()['plan_relation_version']).unlink()
        with self.assertRaisesRegex(InputError,'plan_relations results are missing'):
            worker._publish(self.store,identifier,definition,self.run,root)
        self.assertTrue(semantic_catalog.load(self.run,observed['observer'],self.store)['available'])

    def test_follow_process_retains_protocol_and_publishes_later_cached_arrival(self):
        self.begin();args=[sys.executable,'-X','utf8','-m','rilldex.models','watch',str(self.root/'watch'),
            '--db',str(self.store.path),'--experiment','training','--from-pilot',str(self.pilot),'--follow','--poll-seconds','1']
        child=subprocess.Popen(args,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True)
        try:
            def wait_for(count):
                deadline=time.monotonic()+25
                while time.monotonic()<deadline:
                    if child.poll() is not None:self.fail(child.stderr.read())
                    if (self.root/'watch/watch.json').exists():
                        result=worker.status(self.store,self.root/'watch')
                        if result['current_published']==count:return result
                        if result['job_counts'].get('failed'):
                            child.terminate();child.wait(timeout=10)
                            self.fail(json.dumps(result['jobs'])+' '+child.stderr.read())
                    time.sleep(.1)
                self.fail('Follow process did not publish: '+json.dumps(worker.status(self.store,self.root/'watch')))
            first=wait_for(1)
            # Preseed authored cached requests for a source not yet delivered.
            # The separate test above exercises fresh inference and its ledger.
            from tracker import semantic_workspace as workspace
            later=source('arriving',3);root=self.root/'watch/runs'/later['id']
            definition=read(self.root/'watch/watch.json')
            workspace.initialize(root,later,**definition['workspace_options'])
            workspace.execute(root,transport,command=[sys.executable,'-m','rilldex.candidate'],
                producer=definition['producer'],budget_limits=dict(candidate_requests=100,jev_requests=100,input_bytes=5000000))
            self.store.add([later]);state=wait_for(2)
            self.assertEqual(state['job_counts'],{'published':2})
            self.assertEqual(state['used'],worker.ZERO)
            self.assertEqual(state['observer'],first['observer'])
        finally:
            child.terminate();child.wait(timeout=10);child.stderr.close()


if __name__=='__main__':unittest.main()
