"""Installed workflow restart and offline package refresh; authored decisions."""
from copy import deepcopy
from pathlib import Path
import json
import subprocess
import sys
import unittest
from unittest.mock import patch

from rilldex import models,candidate
from tracker import semantic_watch as worker,semantic_refresh,semantic_catalog,monitoring
from tracker.jev import DEFAULT_MODEL
from tracker.schema import InputError
from tracker.semantic_extraction import read,write
from tracker.store import Store
from tests import test_installed_models as installed
from tests.test_pilot_execution_reports import transport
from tests.test_continuous_behavior import source


class RefreshTests(unittest.TestCase):
    setUp=installed.InstalledModelTests.setUp

    def setup_worker(self,*,old_plan=False):
        self.store=Store(self.root/'db.sqlite');self.run=source();self.store.add([self.run]);self.pilot=self.root/'pilot';self.work=self.root/'watch'
        if old_plan:
            from tracker.action_targets import PAGED_VERSION as WORK
            from tracker.plan_relations import PAGED_VERSION as PLAN
            from tracker.execution_reports import VERSION as REPORT
            config=candidate.settings()
            write(self.pilot/'model.json',dict(adapter=candidate.VERSION,endpoint=config['endpoint'],model=config['model'],decision_model=DEFAULT_MODEL,
                action_target_version=WORK,plan_relation_version=PLAN,execution_report_version=REPORT))
        models.pilot(self.store,self.pilot,self.run['id'],candidate_calls=100,decision_calls=100,input_bytes=5000000,transport=transport)
        return models.watch(self.store,self.work,experiment='training',from_pilot=self.pilot,label='Saved observer',live_prefixes=True)

    def test_restart_uses_saved_protocol_cache_label_and_prefix_policy_without_pilot_argument(self):
        original=self.setup_worker(old_plan=True);count=len(self.calls)
        current=models.watch(self.store,self.work,experiment='training',transport=lambda _:self.fail('Restart must not call a model'))
        self.assertEqual(current['observer'],original['observer'])
        self.assertEqual(current['workspace_options']['plan_relation_version'],'plan-stage-correspondence/3')
        self.assertNotEqual(current['workspace_options'],worker.behavior_options())
        self.assertEqual(current['label'],'Saved observer');self.assertTrue(current['live_prefixes'])
        self.assertEqual(len(self.calls),count)
        self.assertEqual(current['used'],original['used'])

    def test_offline_refresh_keeps_maps_measurements_usage_and_monitor_pauses(self):
        with patch.object(worker,'fingerprint',return_value='previous-package'):
            original=self.setup_worker()
        before=semantic_catalog.load(self.run,original['observer'],self.store);count=len(self.calls)
        monitoring.enabled(self.store,original['monitors'][0],False)
        self.assertEqual(worker.status(self.store,self.work)['implementation']['status'],'needs_refresh')
        with self.assertRaisesRegex(InputError,'implementation changed'):
            models.watch(self.store,self.work,experiment='training',transport=lambda _:self.fail('No calls before refresh'))
        current=models.watch(self.store,self.work,experiment='training',refresh_worker=True,transport=lambda _:self.fail('Refresh must not infer'))
        self.assertEqual(current['implementation']['status'],'current')
        self.assertEqual(current['implementation']['refresh']['checked_jobs'],1)
        self.assertEqual(current['observer'],original['observer']);self.assertEqual(current['used'],original['used'])
        self.assertEqual(semantic_catalog.load(self.run,original['observer'],self.store),before)
        self.assertFalse(next(m for m in monitoring.definitions(self.store) if m['id']==original['monitors'][0])['enabled'])
        self.assertEqual(len(self.calls),count)
        again=semantic_refresh.refresh(self.store,self.work)
        self.assertEqual(again['provider_calls'],0)
        self.assertEqual(len(again['implementation']['refresh']['jobs']),1)
        self.store.add([source('after-update',2)])
        resumed=models.watch(self.store,self.work,experiment='training',candidate_calls=100,decision_calls=100,input_bytes=5000000,transport=transport)
        self.assertEqual(resumed['current_published'],2);self.assertEqual(resumed['observer'],original['observer'])
        self.assertGreater(resumed['used']['jev_requests'],0)
        self.assertEqual(semantic_catalog.load(self.run,original['observer'],self.store),before)

    def test_changed_projection_cannot_be_refreshed_under_the_same_observer(self):
        with patch.object(worker,'fingerprint',return_value='previous-package'):
            original=self.setup_worker()
        materialize=worker.materialize
        def changed(*args):
            result=deepcopy(materialize(*args));result['document']['provenance']['changed_projection']=True;return result
        with patch.object(worker,'materialize',side_effect=changed),self.assertRaisesRegex(InputError,'map differs'):
            semantic_refresh.refresh(self.store,self.work)
        state=worker.status(self.store,self.work)
        self.assertEqual(state['implementation']['status'],'needs_refresh')
        self.assertEqual(state['used'],original['used'])
        self.assertEqual(state['job_counts'],{'published':1})

    def test_refresh_retains_budget_stop_and_partial_decision_cache(self):
        self.store=Store(self.root/'partial.sqlite');run=source();self.store.add([run]);work=self.root/'partial'
        with patch.object(worker,'fingerprint',return_value='previous-package'):
            original=models.watch(self.store,work,experiment='training',candidate_calls=100,decision_calls=2,input_bytes=5000000,transport=transport)
        self.assertEqual(original['job_counts'],{'budget_reached':1})
        count=len(self.calls);semantic_refresh.refresh(self.store,work)
        retained=worker.status(self.store,work)
        self.assertEqual(retained['used'],original['used']);self.assertEqual(retained['allowance'],original['allowance'])
        self.assertEqual(retained['job_counts'],original['job_counts']);self.assertEqual(len(self.calls),count)
        seen=[]
        def decide(req):seen.append(req['state']['stage']);return transport(req)
        resumed=models.watch(self.store,work,experiment='training',decision_calls=100,retry_runs=[run['id']],transport=decide)
        self.assertEqual(resumed['current_published'],1)
        self.assertEqual(resumed['used']['jev_requests'],original['used']['jev_requests']+len(seen))

    def test_refresh_cli_is_offline_and_rejects_changed_source(self):
        with patch.object(worker,'fingerprint',return_value='previous-package'):
            original=self.setup_worker()
        script=[sys.executable,'-X','utf8','-m','rilldex','--db',str(self.store.path),'semantic','watch-refresh',str(self.work)]
        result=subprocess.run(script,capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['provider_calls'],0)
        self.assertEqual(worker.status(self.store,self.work)['used'],original['used'])
        root=self.work/'runs'/self.run['id'];path=root/'runs'/f"{self.run['id']}.json"
        changed=read(path);changed['events'][0]['text']='tampered';write(path,changed)
        with patch.object(worker,'fingerprint',return_value='next-package'),self.assertRaisesRegex(InputError,'source changed'):
            semantic_refresh.refresh(self.store,self.work)

    def test_interrupted_provider_attempt_is_not_retried_or_refunded_by_refresh(self):
        store=Store(self.root/'failed.sqlite');run=source();store.add([run]);work=self.root/'failed'
        def timeout(_):raise TimeoutError('unknown remote completion')
        with patch.object(worker,'fingerprint',return_value='previous-package'):
            original=models.watch(store,work,experiment='training',candidate_calls=100,decision_calls=100,input_bytes=5000000,transport=timeout)
        self.assertEqual(original['job_counts'],{'failed':1})
        self.assertEqual(original['used']['jev_requests'],1)
        count=len(self.calls);semantic_refresh.refresh(store,work)
        stopped=models.watch(store,work,experiment='training',transport=lambda _:self.fail('Refresh cannot retry an unknown attempt'))
        self.assertEqual(stopped['job_counts'],original['job_counts']);self.assertEqual(stopped['used'],original['used'])
        self.assertEqual(len(self.calls),count)
        seen=[]
        def decide(req):seen.append(req);return transport(req)
        done=models.watch(store,work,experiment='training',retry_runs=[run['id']],transport=decide)
        self.assertEqual(done['current_published'],1)
        self.assertEqual(done['used']['jev_requests'],1+len(seen))

    def test_refresh_requires_existing_worker_and_boolean_options(self):
        store=Store(self.root/'empty.sqlite')
        with self.assertRaisesRegex(InputError,'existing worker'):
            models.watch(store,self.root/'missing',experiment='training',refresh_worker=True)
        with self.assertRaisesRegex(InputError,'live_prefixes'):
            models.watch(store,self.root/'missing',experiment='training',live_prefixes='false')
        self.assertFalse((self.root/'missing/watch.json').exists())


if __name__=='__main__':unittest.main()
