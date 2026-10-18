"""Late verifier reports cannot silently leave stale custom findings current."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import unittest
from urllib.request import Request,urlopen
from urllib.error import HTTPError

from tracker import evaluation_receipts as receipts,monitoring,monitor_evidence
from tracker.monitor_evaluation_inputs import KEY,validate,compare
from tracker.schema import InputError,digest
from tracker.workspace_analysis import Workspace
import test_reward_detectors as fixture
from test_evaluation_receipts import report


class EvaluationInputTests(unittest.TestCase):
    setUp=fixture.RewardDetectorTests.setUp
    add=fixture.RewardDetectorTests.add
    start_server=fixture.RewardDetectorTests.start_server
    stop_server=staticmethod(fixture.RewardDetectorTests.stop_server)

    def detector(self,**changes):
        options=dict(version='1',description='Compare explicit evaluator reports',reward_definition='delivery/v3',
            inputs={'reward':'/outcome/recorded_reward'},evaluations={
                'reward':{'purpose':'reward','producer':'scorer/1'},
                'check':{'purpose':'independent_check','producer':'verifier/1'}})
        options.update(changes)
        return Workspace(self.db,observer='source',experiment='train').reward_detector('Verifier agreement',**options)

    def record(self,run,purpose='reward',verdict='passed',**changes):
        raw=report(run,purpose=purpose,verdict=verdict)
        raw['producer']='scorer/1' if purpose=='reward' else 'verifier/1'
        raw.update(changes)
        return receipts.receive(self.store,raw)

    @staticmethod
    def detect(ctx):
        comparison=ctx.compare_evaluations('reward','check');status=comparison['status']
        return dict(status='flagged' if status=='disagreement' else 'clear' if status=='agreement' else 'unknown',
            summary='Evaluator comparison: '+status,
            evaluation_ids=sorted({r['id'] for rows in ctx.evaluations.values() for r in rows}),
            details=comparison)

    def row(self,m,r):
        return next(row['measurement'] for row in monitoring.cases(self.store,m.id)['rows'] if row['run']['id']==r['id'])

    def test_late_reports_invalidate_chart_and_sql_then_recompute_only_affected_run(self):
        a=self.add('a');self.add('b');m=self.detector()
        self.assertEqual(m.run(self.detect)['published'],2)
        first=self.row(m,a);before=monitoring.fingerprint(self.store)
        self.assertEqual(first['details']['custom']['status'],'missing_reports')
        left=self.record(a);right=self.record(a,'independent_check','failed')
        self.assertNotEqual(before,monitoring.fingerprint(self.store))
        self.assertEqual(self.row(m,a)['status'],'pending')
        rows=Workspace(self.db).sql('SELECT run_id FROM monitor_values WHERE monitor_id=?',[m.id]).rows
        self.assertEqual(rows,[{'run_id':'run-b'}])
        self.assertEqual(m.run(self.detect),dict(published=1,skipped=1,waiting=0,errors=0,paused=False))
        finding=self.row(m,a);self.assertEqual(finding['value'],1)
        proof=monitor_evidence.read(self.store,finding['id'])
        self.assertEqual({r['receipt']['id'] for r in proof['explanation']['evaluation_reports']},{left['id'],right['id']})
        old=monitor_evidence.read(self.store,first['id'])
        self.assertEqual(old['explanation']['evaluation_inputs'],{'check':[],'reward':[]})
        self.assertFalse(old['freshness']['current_input'])
        self.assertEqual(m.run(lambda _:self.fail('Cached reports should not run again'))['skipped'],2)

    def test_duplicate_delivery_and_unselected_reports_do_not_invalidate(self):
        a=self.add('a');m=self.detector();left=self.record(a);self.record(a,'independent_check','failed');m.run(self.detect)
        previous=self.row(m,a)['id']
        raw={k:v for k,v in left.items() if k!='id'};receipts.receive(self.store,raw)
        self.record(a,'repair_check');self.record(a,'independent_check',producer='unselected/1')
        self.assertEqual(m.run(lambda _:self.fail('Unselected report'))['skipped'],1)
        self.assertEqual(self.row(m,a)['id'],previous)

    def test_multiple_matching_reports_are_ambiguous_and_old_findings_stay_readable(self):
        a=self.add('a');m=self.detector();self.record(a);self.record(a,'independent_check','failed');m.run(self.detect)
        old=self.row(m,a)
        self.record(a,'independent_check','passed',performed_at='2026-10-16T13:00:00Z')
        m.run(self.detect);new=self.row(m,a)
        self.assertIsNone(new['value']);self.assertEqual(new['details']['custom']['status'],'ambiguous_reports')
        self.assertEqual(new['details']['custom']['counts'],{'check':2,'reward':1})
        proof=monitor_evidence.read(self.store,old['id'])
        self.assertEqual(len(proof['explanation']['evaluation_reports']),2)
        self.assertEqual(proof['measurement']['value'],1);self.assertFalse(proof['freshness']['current_input'])

    def test_arrival_during_callback_rejects_stale_publication_without_stopping_other_runs(self):
        a=self.add('a');self.add('b');m=self.detector();self.record(a)
        def arrive(ctx):
            if ctx.run['id']==a['id']:self.record(a,'independent_check','failed')
            return self.detect(ctx)
        result=m.run(arrive)
        self.assertEqual(result,dict(published=1,skipped=0,waiting=1,errors=0,paused=False))
        self.assertEqual(m.run(self.detect)['published'],1)
        self.assertEqual(self.row(m,a)['value'],1)

    def test_criterion_mismatch_error_and_unknown_are_not_clean_negatives(self):
        for name,status in [('scope','different_inputs'),('error','execution_error'),('unknown','unresolved')]:
            a=self.add(name);self.record(a);raw=report(a,purpose='independent_check',verdict='failed');raw['producer']='verifier/1'
            if name=='scope':raw['inputs']['criterion']['sha256']=digest('different criterion')
            if name=='error':raw.update(execution='error',verdict='unknown',score=None)
            if name=='unknown':raw.update(verdict='unknown',score=None)
            receipts.receive(self.store,raw)
        m=self.detector();m.run(self.detect)
        for row in monitoring.cases(self.store,m.id)['rows']:
            self.assertIsNone(row['measurement']['value']);self.assertEqual(row['measurement']['unknown'],1)
        statuses={r['measurement']['details']['custom']['status'] for r in monitoring.cases(self.store,m.id)['rows']}
        self.assertEqual(statuses,{'different_inputs','execution_error','unresolved'})

    def test_remote_cannot_omit_new_inputs_or_cite_another_run(self):
        a=self.add('a');b=self.add('b');m=self.detector();left=self.record(a);right=self.record(a,'independent_check','failed');m.run(self.detect)
        proof=monitor_evidence.read(self.store,self.row(m,a)['id']);body=deepcopy(proof['input_record']);body.pop('schema')
        body['dependencies']['attempt']=2
        other=self.record(b)
        body['result']['evaluation_ids']=[other['id']]
        with self.assertRaisesRegex(InputError,'outside the pinned'):
            m.monitor.publish(**{k:v for k,v in body.items() if k!='monitor_id'})
        body['result']['evaluation_ids']=[left['id'],right['id']]
        endpoint=self.start_server()
        with urlopen(endpoint+'/api/monitoring/custom-inputs?monitor='+m.id+'&run='+a['id']) as response:
            snapshot=json.load(response)
        self.assertEqual(snapshot,m.monitor.input_snapshot(a['id']))
        self.assertEqual(snapshot['dependencies'][KEY],body['dependencies'][KEY])
        self.assertEqual(snapshot['evaluations']['check'][0]['id'],right['id'])
        self.record(a,'independent_check','passed',performed_at='2026-10-16T13:00:00Z')
        with self.assertRaises(HTTPError) as error:
            urlopen(Request(endpoint+'/api/monitoring/custom-values',data=json.dumps(body).encode(),headers={'Content-Type':'application/json'}))
        self.assertEqual(error.exception.code,400)
        self.assertIn('Evaluator inputs changed',error.exception.read().decode())

    def test_selector_validation_exact_filters_and_same_report_comparison(self):
        for invalid in [{}, {'x':{}}, {'x':{'purpose':'newest'}}, {'bad name':{'purpose':'reward'}},
            {'x':{'purpose':'reward','criterion_sha256':'not-a-hash'}}, {'x':{'purpose':'reward','latest':True}}]:
            with self.assertRaises(InputError):validate(invalid)
        a=self.add('a');self.record(a);self.record(a,'independent_check','failed')
        selector={'purpose':'independent_check','producer':'verifier/1','label':'Original verifier','criterion_sha256':digest('criterion')}
        m=self.detector(evaluations={'reward':{'purpose':'reward'},'check':selector});m.run(self.detect)
        self.assertEqual(self.row(m,a)['value'],1)
        self.assertEqual(compare({'a':[{'id':'same'}],'b':[{'id':'same'}]},'a','b')['status'],'same_report')
        with self.assertRaises(InputError):m.run(self.detect,dependencies={KEY:{}})

    @unittest.skipUnless(shutil.which('node'),'Node executes the actual UI-generated template')
    def test_generated_evaluator_worker_handles_late_negative_scores_and_conflicts(self):
        a=self.add('a',reward=-2)
        options=dict(template='evaluations',database=str(self.db),experiment='train',rewardDefinition='delivery/v3',
            rewardProducer='scorer/1',checkProducer='verifier/1')
        code=subprocess.run([shutil.which('node'),'-e',
            "const {script}=require('./tracker/web/custom-monitor-setup.js');process.stdout.write(script(JSON.parse(require('node:fs').readFileSync(0,'utf8'))));"],
            input=json.dumps(options),text=True,encoding='utf-8',capture_output=True,check=True,
            cwd=Path(__file__).resolve().parents[1]).stdout
        namespace={'__name__':'generated_test'};exec(compile(code,'generated_evaluator.py','exec'),namespace)
        m,detect=namespace['monitor'],namespace['detect']
        m.run(detect);self.assertEqual(self.row(m,a)['details']['detector']['status'],'unknown')
        self.record(a,score=-2);self.record(a,'independent_check','failed',score=-9)
        m.run(detect);self.assertEqual(self.row(m,a)['value'],1)
        self.record(a,'independent_check','passed',score=-1,performed_at='2026-10-16T13:00:00Z')
        m.run(detect);self.assertEqual(self.row(m,a)['details']['custom']['comparison']['status'],'ambiguous_reports')

    def test_interleaved_report_batches_preserve_values_and_only_recompute_changed_inputs(self):
        runs=[self.add(str(i)) for i in range(16)];m=self.detector()
        self.assertEqual(m.run(self.detect)['published'],16)
        completed=set()
        for wave in range(4):
            batch=[i for i in range(15,-1,-1) if i%4==wave]
            for i in batch:
                self.record(runs[i],'independent_check','failed' if i%3==0 else 'passed')
                self.record(runs[i])
            counts=m.run(self.detect);self.assertEqual((counts['published'],counts['skipped'],counts['errors']),(4,12,0))
            completed.update(batch)
            for i,r in enumerate(runs):
                self.assertEqual(self.row(m,r)['value'],int(i%3==0) if i in completed else None)
        values=Workspace(self.db).sql('SELECT value FROM monitor_values WHERE monitor_id=?',[m.id]).rows
        self.assertEqual(len(values),16);self.assertEqual(sum(r['value'] for r in values),6)


if __name__=='__main__':unittest.main()
