"""Lifecycle/fault controls. Fixture decisions do not measure semantic accuracy."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from tracker import semantic_watch as watch, semantic_catalog, semantic_workspace
from tracker.adapters import normalize
from tracker.schema import InputError, digest, dumps
from tracker.semantic_extraction import read, write
from tracker.store import Store
from tests.test_semantic_workspace import GENERATOR
from tests.test_semantic_extraction import response, proposals


def document(name='one'):
    return {'schema_version':'ATIF-v1.7','session_id':name,'agent':{'name':'test','version':'1'},'steps':[
        {'step_id':1,'source':'agent','message':'The reproduction code lacks the decorator. We need to add it to the class to replicate the issue.'}]}


class SemanticWatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.work = self.root/'watch'
        self.store = Store(self.root/'db.sqlite')
        self.script = self.root/'candidate.py'; self.script.write_text(GENERATOR, encoding='utf-8')
        self.command = [sys.executable, str(self.script)]
        self.cap = {'jev_requests':30,'candidate_requests':30,'input_bytes':1_000_000}

    def init(self, **kwargs):
        return watch.initialize(self.store, self.work, experiment='trial', label='Semantic activities',
             command=self.command, producer='authored control/1', allowance=kwargs.pop('allowance', self.cap), **kwargs)

    def init_file(self, **kwargs):
        return watch.initialize(self.store, self.work, experiment='trial', label='Semantic activities',
             allowance=kwargs.pop('allowance', self.cap), **kwargs)

    def source(self, name='one'):
        run = normalize(document(name),'auto',{'experiment':'trial'})[0]
        self.store.add([run]); return run

    def ingest(self, revision, state='complete', name='live', experiment='trial'):
        return self.store.ingest({'producer':'agent','rollout_id':name,'revision':revision,'state':state,
            'document':document(name+str(revision)),'metadata':{'experiment':experiment}})['id']

    def run_worker(self, transport=response, **kwargs):
        return watch.run_once(self.store,self.work,transport,command=self.command,**kwargs)

    def run_file_worker(self, transport=response, **kwargs):
        return watch.run_once(self.store,self.work,transport,**kwargs)

    def supply_file_candidates(self, run_id):
        root=self.work/'runs'/run_id
        waiting=semantic_workspace.status(root)['requests_without_responses']
        for row in waiting:
            req=read(row['request_path']);key=row['request_hash']
            if row['stage']=='partition':
                source=req['source']
                answer={'request_hash':key,'producer':'test file handoff/1',
                    'partitions':[{'spans':[{'start':source['start'],'end':source['end']}],
                                   'contributions':['Describes the recorded contribution.'],
                                   'rationale':'One coherent contribution with its supporting context.'}]}
            elif row['stage']=='activity_readings':
                answer={'request_hash':key,'producer':'test file handoff/1',
                    'readings':[{'activity':'orient','text':'States the immediate task situation.',
                                 'evidence':[req['source']]}]}
            else:
                answer=proposals(req)
            write(root/'candidates'/'responses'/f'{key}.json',answer)
        return waiting

    def measured(self, observer):
        with self.store.connect() as c:
            return [dict(r) for r in c.execute('SELECT * FROM rollout_measurements WHERE observer=?',(observer,))]

    def test_stable_observer_for_new_sources_and_no_repeat_calls(self):
        observer=self.init()['observer']; run=self.source()
        first=self.run_worker()
        self.assertEqual(first['job_counts'],{'published':1})
        self.assertEqual(first['used']['jev_requests'],3)
        bundle=semantic_catalog.load(run,observer,self.store)
        self.assertEqual(bundle['document']['source_hash'],digest(run))
        self.assertEqual(bundle['raw_extraction']['units'][0]['activity'],'orient')
        repeat=self.run_worker(lambda _:self.fail('Published run must not call a provider'))
        self.assertEqual(first['used'],repeat['used'])
        self.source('two'); second=self.run_worker()
        self.assertEqual(second['observer'],observer)
        self.assertEqual(second['current_published'],2)
        self.assertEqual(len(self.measured(observer)),2)
        with patch.object(semantic_catalog,'PROFILES',{}):
            self.assertEqual(len(semantic_catalog.catalog(self.store)['maps']),2)

    def test_worker_token_usage_survives_restart_and_distinguishes_missing_from_zero(self):
        from tracker.semantic_budget import ExecutionBudget
        observer=self.init()['observer']; run=self.source()
        budget=ExecutionBudget(self.work/'usage-control',1,self.cap,
                               ledger=watch.Ledger(self.store,observer,run['id']))
        reported=[{'input_tokens':12,'output_tokens':2,'total_tokens':True},
                  {'input_tokens':0}, {'input_tokens':-1,'output_tokens':'9'}]
        for i,counts in enumerate(reported):
            budget.invoke('jev',{'state':{'stage':'activity'},'control':i},lambda counts=counts:{'usage':counts})
        def failure():raise RuntimeError('private transport error')
        with self.assertRaises(RuntimeError):budget.invoke('jev',{'state':{'stage':'content'}},failure)
        budget.invoke('candidate',{'stage':'content'},lambda:{})
        # A crash can leave a reserved invocation without a completion receipt.
        watch.Ledger(self.store,observer,run['id']).reserve({'attempt_id':'unfinished-control',
            'provider':'jev','input_bytes':100,'status':'started'})
        before=watch.status(self.store,self.work)
        self.store=Store(self.store.path)
        after=watch.status(self.store,self.work)
        self.assertEqual(before['provider_usage'],after['provider_usage'])
        usage=after['provider_usage']['providers']['jev']
        self.assertEqual(usage['attempts'],5)
        self.assertEqual(usage['reported_usage'],{'input_tokens':12,'output_tokens':2})
        self.assertEqual(usage['usage_observations'],{'input_tokens':2,'output_tokens':1})
        self.assertEqual(usage['attempts_without_reported_usage'],3)
        self.assertEqual(usage['statuses'],{'returned':3,'failed_or_interrupted':1,'started':1})
        self.assertEqual(usage['stages'],{'activity':3,'content':1,'unrecorded':1})
        candidate=after['provider_usage']['providers']['candidate']
        self.assertEqual(candidate['reported_usage'],{})
        self.assertEqual(candidate['attempts_without_reported_usage'],1)
        self.assertEqual(after['used'],budget.used|{'jev_requests':5,'input_bytes':budget.used['input_bytes']+100})
        self.assertNotIn('private transport error',dumps(after))

    def test_lifetime_cap_survives_restart_explicit_retry_and_reinitialization(self):
        self.init(allowance={**self.cap,'jev_requests':1}); rid=self.source()['id']
        first=self.run_worker()
        self.assertEqual(first['job_counts'],{'budget_reached':1})
        self.assertEqual(first['used']['jev_requests'],1)
        self.store=Store(self.store.path)
        self.init()  # Reinitializing cannot refill/replace the first allowance.
        self.assertEqual(watch.status(self.store,self.work)['allowance']['jev_requests'],1)
        retry=self.run_worker(lambda _:self.fail('Restart must not refill allowance'),retry_runs=[rid])
        self.assertEqual(retry['used'],first['used'])
        self.assertEqual(self.measured(retry['observer']),[])
        watch.set_allowance(self.store,self.work,{**self.cap,'jev_requests':3})
        self.assertTrue(self.run_worker()['paused_for_review'])
        complete=self.run_worker(retry_runs=[rid])
        self.assertEqual(complete['job_counts'],{'published':1})
        self.assertEqual(complete['used']['jev_requests'],3)
        with self.assertRaises(InputError):watch.set_allowance(self.store,self.work,{**self.cap,'jev_requests':2})

    def test_provider_error_is_retained_without_automatic_retry_or_cross_job_spend(self):
        self.init(); first=self.source()['id']; self.source('two')
        def unavailable(_):raise RuntimeError('secret API error text')
        failed=self.run_worker(unavailable)
        self.assertEqual(failed['job_counts'],{'failed':1,'queued':1})
        self.assertNotIn('secret API error text',dumps(failed))
        self.assertEqual(failed['attempt_statuses'],{'returned':1,'failed_or_interrupted':1})
        self.assertEqual(self.run_worker(lambda _:self.fail('Outage must pause worker'))['used'],failed['used'])
        complete=self.run_worker(retry_runs=[first])
        self.assertEqual(complete['job_counts'],{'published':2})
        self.assertEqual(complete['used']['jev_requests'],7)  # Includes failed reservation.

    def test_invalid_model_response_is_not_published_and_wire_is_saved(self):
        self.init(); rid=self.source()['id']
        failed=self.run_worker(lambda _:{'model':'invalid','answers':{}})
        self.assertEqual(failed['job_counts'],{'failed':1})
        self.assertEqual(self.measured(failed['observer']),[])
        wire=list((self.work/'runs'/rid/'wire').rglob('*.json'))
        self.assertEqual(read(wire[0])['response']['model'],'invalid')

    def test_candidate_fault_survives_restart_and_explicit_retry_keeps_evidence(self):
        flag=self.root/'failed-once'
        self.script.write_text(f"from pathlib import Path\np=Path({str(flag)!r})\nif not p.exists():\n p.touch(); __import__('sys').stdout.buffer.write(b'\\xff'); raise SystemExit(0)\n"+GENERATOR,encoding='utf-8')
        self.init();self.source('one');self.source('two')
        failed=self.run_worker(lambda _:self.fail('Malformed candidates cannot reach Jev'))
        self.assertEqual(failed['job_counts'],{'failed':1,'queued':1})
        job=next(j for j in failed['jobs'] if j['status']=='failed')
        self.assertEqual(job['details']['provider_failure']['category'],'invalid_utf8')
        self.assertEqual(failed['used']['candidate_requests'],1)
        self.assertEqual(failed['used']['jev_requests'],0)
        with self.store.connect() as c:
            rows=[json.loads(r[0]) for r in c.execute('SELECT document FROM semantic_watch_attempts')]
        self.assertEqual(rows[0]['provider_failure']['category'],'invalid_utf8')
        self.store=Store(self.store.path)
        stopped=self.run_worker(lambda _:self.fail('Polling cannot retry failed proposer'))
        self.assertEqual(stopped['used'],failed['used'])
        complete=self.run_worker(retry_runs=[job['run_id']])
        self.assertEqual(complete['current_published'],2)
        receipts=[read(p) for p in (self.work/'runs'/job['run_id']/'candidates/receipts/attempts').glob('*.json')]
        self.assertEqual(sum(r['status']=='failed' for r in receipts),1)
        self.assertTrue(any(r['status']=='candidate_ready' for r in receipts))
        repeat=self.run_worker(lambda _:self.fail('Completed results must replay'))
        self.assertEqual(repeat['used'],complete['used'])

    def test_new_revision_arriving_during_extraction_prevents_stale_publication(self):
        self.init(); old=self.ingest(0)
        replaced=[]
        def transport(req):
            if not replaced:replaced.append(self.ingest(1))
            return response(req)
        result=self.run_worker(transport)
        self.assertEqual(result['job_counts'],{'superseded':1})
        self.assertEqual(self.measured(result['observer']),[])
        result=self.run_worker()
        self.assertEqual(result['job_counts'],{'superseded':1,'published':1})
        self.assertEqual(self.measured(result['observer'])[0]['run_id'],replaced[0])

    def test_incomplete_revisions_wait_and_ready_backlog_is_bounded(self):
        self.init(); self.ingest(0,'in_progress')
        for i in range(4):self.source(str(i))
        first=self.run_worker(max_rollouts=1,max_pending=2)
        self.assertEqual(first['waiting_for_completion'],1)
        self.assertEqual(first['not_queued'],2)
        self.assertEqual(first['job_counts'],{'published':1,'queued':1})
        self.ingest(1)
        for _ in range(4):last=self.run_worker(max_rollouts=1,max_pending=2)
        self.assertEqual(last['current_published'],5)

    def test_revision_changed_while_queued_is_skipped_before_provider_spend(self):
        self.init(); self.ingest(0,name='first'); old=self.ingest(0,name='second')
        calls=[]
        def transport(req):
            if not calls:self.ingest(1,name='second')
            calls.append(req)
            return response(req)
        result=self.run_worker(transport)
        self.assertEqual(len(calls),3)
        self.assertEqual(result['job_counts'],{'published':1,'superseded':1})
        self.assertFalse((self.work/'runs'/old).exists())

    def test_identical_revisions_use_latest_lifecycle_state_and_reuse_observation(self):
        self.init()
        payload={'producer':'agent','rollout_id':'identical','revision':0,'state':'in_progress',
                 'document':document(),'metadata':{'experiment':'trial'}}
        first=self.store.ingest(payload)['id']
        self.assertEqual(self.run_worker()['waiting_for_completion'],1)
        payload.update(revision=1,state='complete')
        self.assertEqual(self.store.ingest(payload)['id'],first)
        done=self.run_worker();self.assertEqual(done['current_published'],1)
        payload.update(revision=2);self.store.ingest(payload)
        repeated=self.run_worker(lambda _:self.fail('Unchanged source requires no new observation'))
        self.assertEqual(repeated['current_published'],1);self.assertEqual(repeated['used'],done['used'])

    def test_lifecycle_reactivation_cannot_erase_blocked_budget(self):
        self.init(allowance={**self.cap,'jev_requests':1})
        payload={'producer':'agent','rollout_id':'same','revision':0,'state':'complete',
                 'document':document(),'metadata':{'experiment':'trial'}}
        self.store.ingest(payload);stopped=self.run_worker()
        self.assertEqual(stopped['job_counts'],{'budget_reached':1})
        payload.update(revision=1,state='in_progress');self.store.ingest(payload)
        self.assertEqual(self.run_worker()['job_counts'],{'superseded':1})
        payload.update(revision=2,state='complete');self.store.ingest(payload)
        resumed=self.run_worker(lambda _:self.fail('Lifecycle change cannot retry blocked inference'))
        self.assertEqual(resumed['job_counts'],{'budget_reached':1})
        self.assertEqual(resumed['used'],stopped['used'])

    def test_publication_is_atomic_and_retry_reuses_provider_results(self):
        self.init(); rid=self.source()['id']
        with patch('tracker.rollout_metrics.record_map',side_effect=RuntimeError('disk failure')):
            failed=self.run_worker()
        self.assertEqual(failed['job_counts'],{'failed':1})
        with self.store.connect() as c:
            exists=c.execute("SELECT 1 FROM sqlite_master WHERE name='observer_archives'").fetchone()
            self.assertEqual(c.execute('SELECT count(*) FROM observer_archives').fetchone()[0] if exists else 0,0)
        self.assertEqual(self.measured(failed['observer']),[])
        done=self.run_worker(lambda _:self.fail('Publication retry must reuse decisions'),retry_runs=[rid])
        self.assertEqual(done['job_counts'],{'published':1})
        self.assertEqual(done['used'],failed['used'])

    def test_process_death_after_reservation_is_unknown_and_does_not_refill(self):
        self.init(); rid=self.source()['id']
        program='''import os,sys
from tracker.store import Store
from tracker.semantic_watch import run_once
run_once(Store(sys.argv[1]),sys.argv[2],lambda _:os._exit(23),command=[sys.executable,sys.argv[3]])
'''
        child=subprocess.run([sys.executable,'-c',program,str(self.store.path),str(self.work),str(self.script)],capture_output=True,text=True)
        self.assertEqual(child.returncode,23,child.stderr)
        abandoned=watch.status(self.store,self.work)
        self.assertEqual(abandoned['job_counts'],{'running':1})
        self.assertEqual(abandoned['attempt_statuses'],{'returned':1,'started':1})
        recovered=self.run_worker(lambda _:self.fail('Recovery cannot resend unknown remote request'))
        self.assertEqual(recovered['job_counts'],{'interrupted':1})
        complete=self.run_worker(retry_runs=[rid])
        self.assertEqual(complete['job_counts'],{'published':1})
        self.assertEqual(complete['used']['jev_requests'],4)
        self.assertEqual(complete['attempt_statuses']['started'],1)

    def test_live_owner_cannot_be_stolen_and_changed_command_cannot_run(self):
        self.init(); self.source()
        with semantic_workspace.exclusive(self.work),self.assertRaisesRegex(InputError,'Another process'):
            self.run_worker()
        with self.assertRaisesRegex(InputError,'command differs'):
            watch.run_once(self.store,self.work,response,command=['something-else'])
        with patch.object(watch,'fingerprint',return_value='different'),self.assertRaisesRegex(InputError,'implementation changed'):
            self.run_worker()

    def test_default_file_mode_queues_candidates_without_any_provider(self):
        watch.initialize(self.store,self.work,experiment='trial',label='File proposals')
        self.source()
        result=watch.run_once(self.store,self.work,lambda _:self.fail('No candidates or allowance'))
        self.assertEqual(result['job_counts'],{'needs_candidates':1})
        self.assertEqual(result['used'],watch.ZERO)

    def test_file_handoff_auto_resumes_each_new_stage_once(self):
        self.init_file();run=self.source();rid=run['id']
        first=self.run_file_worker()
        self.assertEqual(first['job_counts'],{'needs_candidates':1})
        job=next(j for j in first['jobs'] if j['run_id']==rid)
        self.assertGreater(job['details']['waiting_candidates']['missing_responses'],0)
        self.assertNotIn('candidate_handoff',job['details'])
        with self.store.connect() as c:
            saved=json.loads(c.execute('SELECT document FROM semantic_watch_jobs WHERE run_id=?',(rid,)).fetchone()[0])
        self.assertEqual(saved['candidate_handoff']['schema'],'semantic-candidate-handoff/1')

        stages=[]
        for _ in range(4):
            waiting=self.supply_file_candidates(rid)
            stages.extend(row['stage'] for row in waiting)
            result=self.run_file_worker()
            if result['job_counts'].get('published'):
                break
            self.assertEqual(result['job_counts'],{'needs_candidates':1})
        self.assertIn('partition',stages)
        self.assertIn('content',stages)
        self.assertEqual(result['job_counts'],{'published':1})
        repeat=self.run_file_worker(lambda _:self.fail('Unchanged completed handoffs must not resume'))
        self.assertEqual(repeat['used'],result['used'])

    def test_unchanged_rejected_candidate_response_never_repeats_selector(self):
        for rejected in ('no_suitable_candidate','unresolved'):
            with self.subTest(rejected=rejected):
                saved=(self.root,self.work,self.store,self.script,self.command)
                with tempfile.TemporaryDirectory() as temporary:
                    self.root=Path(temporary);self.work=self.root/'watch';self.store=Store(self.root/'db.sqlite')
                    self.script=self.root/'candidate.py';self.script.write_text(GENERATOR,encoding='utf-8')
                    self.command=[sys.executable,str(self.script)]
                    self.init_file();run=self.source();rid=run['id']
                    self.run_file_worker()
                    stopped=None
                    for _ in range(8):
                        pending=semantic_workspace.status(self.work/'runs'/rid)['requests_without_responses']
                        if pending:self.supply_file_candidates(rid)
                        def reject(req):
                            if req.get('state',{}).get('stage')!='content':return response(req)
                            q=req['questions']['choice'];options=list(q['criteria'])
                            return {'model':req['model'],'answers':{'choice':{'type':'choice',
                                'probabilities':{key:1 if key==rejected else 0 for key in options}}}}
                        stopped=self.run_file_worker(reject)
                        checkpoint=read(self.work/'runs'/rid/'checkpoints'/f'{rid}.json')
                        rejected_units=[unit for unit in checkpoint['units']
                                        if unit.get('status')=='needs_content_repair']
                        if rejected_units:
                            break
                    self.assertTrue(rejected_units, 'The workflow must reach content candidate selection')
                    unit=rejected_units[0]
                    self.assertEqual(unit['content_choice'],rejected)
                    decision=read(self.work/'runs'/rid/'decisions'/f"{unit['content_request']}.json")
                    self.assertEqual(decision['answers']['choice']['value'],rejected)
                    self.assertEqual(stopped['job_counts'],{'needs_candidates':1})
                    used=stopped['used']
                    unchanged=self.run_file_worker(lambda _:self.fail('Unchanged rejected response must not repeat selector calls'))
                    self.assertEqual(unchanged['used'],used)
                    self.assertEqual(unchanged['jobs'][0]['details']['waiting_candidates']['responses_present'],
                                     stopped['jobs'][0]['details']['waiting_candidates']['responses_present'])
                self.root,self.work,self.store,self.script,self.command=saved

    def test_legacy_wait_without_fingerprint_is_explicit_even_after_response_arrives(self):
        self.init_file();run=self.source();rid=run['id']
        first=self.run_file_worker()
        self.supply_file_candidates(rid)
        with self.store.connect() as c:
            row=c.execute('SELECT document FROM semantic_watch_jobs WHERE run_id=?',(rid,)).fetchone()
            detail=json.loads(row['document']);detail.pop('candidate_handoff',None);detail.pop('waiting_candidates',None)
            c.execute('UPDATE semantic_watch_jobs SET document=? WHERE run_id=?',(dumps(detail),rid))
        before=first['used']
        result=self.run_file_worker(lambda _:self.fail('Legacy jobs must not opportunistically resume'))
        self.assertEqual(result['job_counts'],{'needs_candidates':1})
        self.assertEqual(result['used'],before)

    def test_changed_response_requeues_once_and_failed_or_budget_jobs_stay_blocked(self):
        self.init_file();run=self.source();rid=run['id']
        self.run_file_worker()
        waiting=semantic_workspace.status(self.work/'runs'/rid)['requests_without_responses']
        partial_path=Path(waiting[0]['request_path']).parent.parent/'responses'/f"{waiting[0]['request_hash']}.json"
        partial_path.parent.mkdir(parents=True,exist_ok=True)
        partial_path.write_bytes(b'{"request_hash":')
        with patch.object(watch.workspace,'execute',wraps=semantic_workspace.execute) as execute:
            partial=self.run_file_worker(lambda _:self.fail('Partial JSON must not trigger execution'))
            self.assertEqual(execute.call_count,0)
        self.assertEqual(partial['job_counts'],{'needs_candidates':1})
        # Remove the partial write; the supported helper publishes complete JSON
        # through a temporary file followed by atomic replacement.
        partial_path.unlink()
        waiting=self.supply_file_candidates(rid)
        # Add insignificant JSON whitespace: content identity changes even when
        # filesystem timestamps could be unchanged.
        response_path=Path(waiting[0]['request_path']).parent.parent/'responses'/f"{waiting[0]['request_hash']}.json"
        response_path.write_bytes(response_path.read_bytes()+b' ')
        with patch.object(watch.workspace,'execute',wraps=semantic_workspace.execute) as execute:
            resumed=self.run_file_worker()
            self.assertEqual(execute.call_count,1)
        self.assertEqual(resumed['job_counts'],{'needs_candidates':1})
        self.assertGreater(resumed['jobs'][0]['details']['waiting_candidates']['changed_responses']['count'],0)
        with patch.object(watch.workspace,'execute',wraps=semantic_workspace.execute) as execute:
            unchanged=self.run_file_worker(lambda _:self.fail('A consumed response change must requeue only once'))
            self.assertEqual(execute.call_count,0)
        self.assertEqual(unchanged['job_counts'],{'needs_candidates':1})

        failed_work=self.root/'failed-worker'
        watch.initialize(self.store,failed_work,experiment='trial',label='Failed file wait',command=self.command,
                         producer='authored control/1',allowance=self.cap)
        run2=self.source('failed')
        def outage(_):raise RuntimeError('temporary provider outage')
        failed=watch.run_once(self.store,failed_work,outage,command=self.command)
        self.assertEqual(failed['job_counts'].get('failed'),1)
        stopped=watch.run_once(self.store,failed_work,lambda _:self.fail('Failed jobs require explicit retry'),command=self.command)
        self.assertEqual(stopped['used'],failed['used'])

    def test_interrupted_job_ignores_later_candidate_changes_until_explicit_retry(self):
        self.init_file();run=self.source();rid=run['id']
        self.run_file_worker()
        waiting=self.supply_file_candidates(rid)
        self.assertTrue(waiting)
        with self.assertRaises(KeyboardInterrupt):
            self.run_file_worker(lambda _:(_ for _ in ()).throw(KeyboardInterrupt()))
        interrupted=watch.status(self.store,self.work)
        self.assertEqual(interrupted['job_counts'],{'interrupted':1})
        response_path=Path(waiting[0]['request_path']).parent.parent/'responses'/f"{waiting[0]['request_hash']}.json"
        response_path.write_bytes(response_path.read_bytes()+b' ')
        stopped=self.run_file_worker(lambda _:self.fail('Changed handoffs cannot retry interrupted work'))
        self.assertEqual(stopped['job_counts'],{'interrupted':1})
        self.assertEqual(stopped['used'],interrupted['used'])

    def test_new_revision_does_not_bypass_failed_or_budget_predecessor(self):
        self.init();old=self.ingest(0,name='failed-chain')
        def outage(_):raise RuntimeError('provider unavailable')
        failed=self.run_worker(outage)
        self.assertEqual(next(j for j in failed['jobs'] if j['run_id']==old)['status'],'failed')
        successor=self.ingest(1,name='failed-chain')
        blocked=self.run_worker(lambda _:self.fail('New revisions cannot bypass failed predecessors'))
        row=next(j for j in blocked['jobs'] if j['run_id']==successor)
        self.assertEqual(row['status'],'failed')
        self.assertEqual(row['details']['inherited_from_run'],old)
        self.assertEqual(blocked['used'],failed['used'])

        budget_work=self.root/'budget-chain-worker'
        watch.initialize(self.store,budget_work,experiment='trial-budget',label='Budget chain',
                         command=self.command,producer='authored control/1',
                         allowance={**self.cap,'jev_requests':0})
        budget_old=self.ingest(0,name='budget-chain',experiment='trial-budget')
        budgeted=watch.run_once(self.store,budget_work,response,command=self.command)
        self.assertEqual(next(j for j in budgeted['jobs'] if j['run_id']==budget_old)['status'],'budget_reached')
        budget_successor=self.ingest(1,name='budget-chain',experiment='trial-budget')
        budget_blocked=watch.run_once(self.store,budget_work,
            lambda _:self.fail('New revisions cannot bypass budget predecessors'),command=self.command)
        row=next(j for j in budget_blocked['jobs'] if j['run_id']==budget_successor)
        self.assertEqual(row['status'],'budget_reached')
        self.assertEqual(row['details']['inherited_from_run'],budget_old)
        self.assertEqual(budget_blocked['used'],budgeted['used'])

    def test_cli_default_budget_and_status_are_keyless(self):
        prefix=[sys.executable,'-m','rilldex','--db',str(self.store.path),'semantic']
        created=subprocess.run(prefix+['watch-init',str(self.work),'--experiment','trial','--label','Base activities'],capture_output=True,text=True)
        self.assertEqual(created.returncode,0,created.stderr)
        self.assertEqual(json.loads(created.stdout)['allowance'],watch.ZERO)
        self.source()
        ran=subprocess.run(prefix+['watch-run',str(self.work)],capture_output=True,text=True)
        self.assertEqual(ran.returncode,0,ran.stderr)
        self.assertEqual(json.loads(ran.stdout)['job_counts'],{'needs_candidates':1})

    def test_follow_process_publishes_cached_existing_and_later_sources(self):
        self.init()
        runs=[normalize(document(name),'auto',{'experiment':'trial'})[0] for name in ('existing','later')]
        for run in runs:
            root=self.work/'runs'/run['id']
            semantic_workspace.initialize(root,run)
            semantic_workspace.execute(root,response,command=self.command,producer='authored control/1')
        self.store.add(runs[:1])
        command=[sys.executable,'-m','rilldex','--db',str(self.store.path),'semantic','watch-run',str(self.work),
                 '--follow','--poll-seconds','1','--candidate-command',*self.command]
        child=subprocess.Popen(command,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True)
        try:
            def await_published(count):
                deadline=time.monotonic()+12
                while time.monotonic()<deadline:
                    if child.poll() is not None:self.fail(child.stderr.read())
                    if watch.status(self.store,self.work)['current_published']==count:return
                    time.sleep(.05)
                self.fail('Follow worker did not publish the newly available source')
            await_published(1)
            self.store.add(runs[1:]);await_published(2)
            self.assertEqual(watch.status(self.store,self.work)['used'],watch.ZERO)
        finally:
            child.terminate();child.wait(timeout=10);child.stderr.close()


if __name__=='__main__':unittest.main()
