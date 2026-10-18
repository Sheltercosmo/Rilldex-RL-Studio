"""Evaluation evidence cannot silently become reward, agent knowledge or a verdict."""
import copy
from contextlib import closing
import json
import sqlite3
import unittest
from urllib.request import Request, urlopen

from rilldex import Workspace
from tracker.analytics import Analysis
from tracker import evaluation_receipts as evaluations, investigation_followups as follow
from tracker import failure_investigations, source_evidence
from tracker.schema import InputError, digest, dumps
import test_failure_investigations as failure_fixture
import test_investigation_followups as follow_fixture
import test_generation_cohort_transport as transport


def report(run, *, purpose='reward', verdict='passed', label='Original verifier'):
    return dict(schema=evaluations.VERSION, label=label, producer='authored-test-worker/1',
                performed_at='2026-10-16T12:00:00Z', run_id=run['id'], source_hash=digest(run),
                purpose=purpose, inputs={role:dict(label=role, sha256=digest(role)) for role in evaluations.INPUTS},
                execution='completed', verdict=verdict, score=1 if verdict=='passed' else 0,
                summary='Authored test evidence; not a real environment evaluation.',
                evidence=[dict(label='Worker output', text='fixture result')])


class EvaluationTests(unittest.TestCase):
    setUp = transport.GenerationCohortTransportTests.setUp
    start_server = transport.GenerationCohortTransportTests.start_server
    stop_server = staticmethod(transport.GenerationCohortTransportTests.stop_server)
    run_fixture = failure_fixture.FailureInvestigationTests.run_fixture
    base = follow_fixture.FollowupTests.base
    plan = follow_fixture.FollowupTests.plan
    finding = follow_fixture.FollowupTests.finding

    def pair(self):
        run=self.run_fixture(reward=1)
        left=report(run)
        right=report(run,purpose='independent_check',verdict='failed',label='Independent verifier')
        right['inputs']['evaluator']['sha256']=digest('different check implementation')
        return run,left,right

    def test_source_citations_bind_exact_text_and_survive_sdk_http_and_followups(self):
        root=self.base();parent=self.plan(root)
        run=self.store.get(root['snapshot']['rows'][0]['id'],raw=True)['run']
        event=next(e for e in run['events'] if e['text'].strip())
        w=Workspace(self.db)
        citation=w.cite_source(run['id'],event['id'],role='context',quote=event['text'])
        raw=report(run);raw['source_citations']=[citation]
        saved=w.record_evaluation(raw)
        self.assertEqual(saved['source_citations'],[citation])
        endpoint=self.start_server()
        req=Request(endpoint+'/api/evaluations',data=json.dumps(raw).encode(),headers={'Content-Type':'application/json'})
        with urlopen(req,timeout=15) as response:self.assertEqual(json.load(response),saved)
        finding=self.finding(parent,evidence=[dict(kind='evaluation',id=saved['id'])],assessment='inconclusive')
        retained=follow.bundle(self.store,finding['id'])['investigation']['follow_up']['checks'][0]['results'][0]
        self.assertEqual(retained['evidence'][0]['receipt']['source_citations'],[citation])
        self.assertEqual(Workspace(self.db).table('evaluations').rows[0]['receipt']['source_citations'],[citation])

    def test_forged_source_citations_are_rejected_without_saving_any_report(self):
        run,left,_=self.pair();event=next(e for e in run['events'] if len(e['text'])>2)
        cite=evaluations.cite_source(run,event['id'],role='implementation')
        mutations=[dict(text='x'+cite['text'][1:]),dict(source_pointer='/wrong'),dict(event_id='missing'),
            dict(source_hash='0'*64),dict(run_id='other'),dict(start=True),dict(end=cite['end']+1),
            dict(role='verified_reward_hack'),dict(basis='utf16'),dict(extra='untrusted')]
        for change in mutations:
            with self.subTest(change=change),self.assertRaises(InputError):
                evaluations.receive(self.store,{**left,'source_citations':[{**cite,**change}]})
        with self.assertRaisesRegex(InputError,'Duplicate'):
            evaluations.receive(self.store,{**left,'source_citations':[cite,cite]})
        self.assertEqual(evaluations.listing(self.store,run_id=run['id'])['receipts'],[])
        denied=Workspace(self.db,experiment='not-this-experiment')
        with self.assertRaisesRegex(InputError,'scope'):
            denied.cite_source(run['id'],event['id'],role='context')

    def test_citation_quote_ambiguity_unicode_offsets_and_legacy_identity(self):
        run,left,_=self.pair();event=run['events'][0]
        event['text']='😀 start repeated repeated 结束'
        cite=evaluations.cite_source(run,event['id'],role='requirement',quote='结束')
        self.assertEqual(cite['start'],26)
        self.assertEqual(evaluations.cite_source(run,event['id'],role='requirement',start=26,end=28),cite)
        for options in [dict(quote='repeated'),dict(quote='absent'),dict(quote='start',start=2),dict(start=-1),dict(end=100)]:
            with self.subTest(options=options),self.assertRaises(InputError):
                evaluations.cite_source(run,event['id'],role='context',**options)
        saved=evaluations.receive(self.store,left)
        self.assertNotIn('source_citations',saved)
        self.assertEqual(saved['id'],'evaluation-'+digest(left))

    def test_bound_report_is_idempotent_and_does_not_change_reward_graph_or_source_search(self):
        run,left,right=self.pair()
        before=self.store.get(run['id'],raw=True)['run']
        anchor=next(e for e in reversed(run['events']) if e['text'])
        query=dict(anchor=dict(event_id=anchor['id']),text='hidden-check-sentinel')
        old=source_evidence.search(run,query)
        right['evidence'][0]['text']='hidden-check-sentinel: failed independent check'
        row=evaluations.receive(self.store,right)
        self.assertEqual(row,evaluations.receive(self.store,right))
        self.assertEqual(before,self.store.get(run['id'],raw=True)['run'])
        self.assertEqual(old,source_evidence.search(self.store.get(run['id'],raw=True)['run'],query))
        self.assertEqual(before['outcome']['recorded_reward'],1)
        self.assertEqual(len(evaluations.listing(self.store,run_id=run['id'])['receipts']),1)

    def test_changed_artifact_or_task_is_not_a_controlled_verifier_disagreement(self):
        _,left,right=self.pair()
        a=evaluations.receive(self.store,left)
        for role in evaluations.MATCH_INPUTS:
            changed=copy.deepcopy(right);changed['inputs'][role]['sha256']=digest('new '+role)
            pair=evaluations.compare(a,evaluations.receive(self.store,changed))
            self.assertEqual(pair['status'],'different_inputs')
            self.assertEqual(pair['different_inputs'],[role])

    def test_missing_pins_errors_and_unknowns_never_count_as_failed_tasks(self):
        _,left,right=self.pair();a=evaluations.receive(self.store,left)
        for role in evaluations.INPUTS:
            missing=copy.deepcopy(right);missing['inputs'][role]=None
            result=evaluations.compare(a,evaluations.receive(self.store,missing))
            self.assertEqual(result['status'],'missing_inputs');self.assertIn(role,result['missing_inputs'])
        for execution,status in [('error','execution_error'),('incomplete','unresolved'),('not_run','unresolved')]:
            pending={**right,'execution':execution,'verdict':'unknown','score':None}
            self.assertEqual(evaluations.compare(a,evaluations.receive(self.store,pending))['status'],status)

    def test_both_disagreement_directions_are_preserved_and_do_not_adjudicate_hacking(self):
        _,left,right=self.pair()
        for original,independent in [('passed','failed'),('failed','passed')]:
            a=evaluations.receive(self.store,{**left,'verdict':original})
            b=evaluations.receive(self.store,{**right,'verdict':independent})
            pair=evaluations.compare(a,b)
            self.assertEqual(pair['status'],'disagreement')
            self.assertEqual([r['verdict'] for r in pair['observations']],[original,independent])
            self.assertNotIn('reward_hacking',pair)
        a=evaluations.receive(self.store,left)
        b=evaluations.receive(self.store,{**right,'verdict':'passed'})
        self.assertEqual(evaluations.compare(a,b)['status'],'agreement')

    def test_same_evaluator_and_unrelated_rollout_remain_explicit(self):
        _,left,right=self.pair()
        right['inputs']['evaluator']=left['inputs']['evaluator']
        a=evaluations.receive(self.store,left);b=evaluations.receive(self.store,right)
        self.assertFalse(evaluations.compare(a,b)['evaluator_changed'])
        other=evaluations.receive(self.store,report(self.run_fixture(nonce=99)))
        self.assertEqual(evaluations.compare(a,other)['status'],'different_source')

    def test_legacy_report_without_criterion_is_readable_but_not_a_controlled_disagreement(self):
        _,left,right=self.pair();right['inputs'].pop('criterion')
        a=evaluations.receive(self.store,left);b=evaluations.receive(self.store,right)
        self.assertEqual(evaluations.read(self.store,b['id']),b)
        pair=evaluations.compare(a,b)
        self.assertEqual(pair['status'],'missing_inputs')
        self.assertIn('criterion',pair['missing_inputs'])
        self.assertEqual(pair['schema'],evaluations.COMPARISON_VERSION)

    def test_bad_fields_stale_sources_and_nonfinite_scores_are_rejected_atomically(self):
        run,left,_=self.pair()
        invalid=[{**left,'source_hash':'0'*64},{**left,'run_id':'missing'},
                 {**left,'score':True},{**left,'score':float('nan')},{**left,'score':10**400},
                 {**left,'purpose':[]},{**left,'execution':'error'},
                 {**left,'performed_at':'2026-10-16T12:00:00'},
                 {**left,'independently_verified':True},{**left,'evidence':[dict(label='x',text='x'*12001)]}]
        bad=copy.deepcopy(left);bad['inputs']['artifact']['sha256']='file:///local';invalid.append(bad)
        bad=copy.deepcopy(left);bad['inputs'].pop('task');invalid.append(bad)
        for row in invalid:
            with self.subTest(row=list(row)),self.assertRaises(InputError):evaluations.receive(self.store,row)
        self.assertEqual(evaluations.listing(self.store,run_id=run['id'])['receipts'],[])

    def test_report_tampering_and_forged_attachment_fail(self):
        _,left,_=self.pair();row=evaluations.receive(self.store,left)
        with self.assertRaises(InputError):follow.evidence(self.store,[dict(kind='evaluation',id=row['id'],receipt={})])
        with self.store.connect() as c:
            c.execute('UPDATE evaluation_receipts SET document=? WHERE id=?',(dumps({**left,'verdict':'failed'}),row['id']))
        with self.assertRaisesRegex(InputError,'identity mismatch'):evaluations.read(self.store,row['id'])
        with self.assertRaises(InputError):follow.evidence(self.store,[dict(kind='evaluation',id=row['id'])])

    def test_late_repair_keeps_old_comparison_findings_and_export(self):
        root=self.base();parent=self.plan(root);run=self.store.get(root['snapshot']['rows'][0]['id'],raw=True)['run']
        original=report(run);check=report(run,purpose='independent_check',verdict='failed')
        check['inputs']['evaluator']['sha256']=digest('independent')
        a=evaluations.receive(self.store,original);b=evaluations.receive(self.store,check)
        refs=[dict(kind='evaluation',id=r['id']) for r in (a,b)]
        saved=self.finding(parent,evidence=refs,assessment='supports',conclusion='Reported checks disagree; review the artifacts.')
        finding=saved['follow_up']['checks'][0]['results'][0]
        self.assertEqual(finding['evaluation_comparisons'][0]['status'],'disagreement')
        repair=copy.deepcopy(check);repair.update(purpose='repair_check',verdict='passed',score=1)
        repair['inputs']['evaluator']['sha256']=digest('repair')
        evaluations.receive(self.store,repair)
        self.assertEqual(failure_investigations.read(self.store,saved['id']),saved)
        bundle=follow.bundle(self.store,saved['id'])
        self.assertEqual(bundle['investigation']['follow_up']['checks'][0]['results'][0],finding)
        self.assertEqual(finding['evidence'][0]['receipt'],a)

    def test_code_scope_pagination_and_invalid_comparisons(self):
        run,left,right=self.pair();w=Workspace(self.db,experiment='test')
        a=w.record_evaluation(left);b=w.record_evaluation(right)
        page=w.evaluations(run['id'],limit=1)
        self.assertTrue(page['more']);self.assertEqual(len(w.evaluations(run['id'],limit=1,offset=1)['receipts']),1)
        self.assertEqual(w.compare_evaluations([a['id'],b['id']])['pairs'][0]['status'],'disagreement')
        rows=w.sql('SELECT evaluation_id,verdict,receipt_json FROM evaluations WHERE run_id=?',[run['id']]).rows
        self.assertEqual({r['evaluation_id'] for r in rows},{a['id'],b['id']})
        self.assertEqual({r['receipt']['purpose'] for r in rows},{'reward','independent_check'})
        denied=Workspace(self.db,experiment='different')
        self.assertEqual(denied.table('evaluations').rows,[])
        for call in [lambda:denied.record_evaluation(left),lambda:denied.evaluations(run['id']),lambda:denied.compare_evaluations([a['id'],b['id']])]:
            with self.assertRaisesRegex(InputError,'scope'):call()
        for ids in [[],[a['id']],[a['id'],a['id']],['missing',b['id']],{}]:
            with self.assertRaises(InputError):w.compare_evaluations(ids)

    def test_http_worker_reports_and_findings_use_same_receipts_as_sdk(self):
        run,left,right=self.pair();endpoint=self.start_server();w=Workspace(self.db)
        def post(path,body):
            req=Request(endpoint+path,data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
            with urlopen(req,timeout=15) as response:return json.load(response)
        a=post('/api/evaluations',left);b=post('/api/evaluations',right)
        self.assertEqual(a,w.record_evaluation(left))
        self.assertEqual(post('/api/evaluations/compare',dict(ids=[a['id'],b['id']])),w.compare_evaluations([a['id'],b['id']]))
        with urlopen(endpoint+'/api/evaluations?run_id='+run['id']) as response:
            self.assertEqual(json.load(response),w.evaluations(run['id']))
        preview=post('/api/investigations/follow-ups/preview',dict(evidence=[dict(kind='evaluation',id=r['id']) for r in (a,b)]))
        self.assertEqual(preview['evaluation_comparisons'][0]['status'],'disagreement')
        self.assertEqual(preview['inference_calls'],0)

    def test_frozen_exports_retain_reports_and_older_workspaces_remain_readable(self):
        run,left,_=self.pair();row=evaluations.receive(self.store,left)
        frozen=self.root/'frozen.sqlite';Analysis(self.db).database(frozen)
        w=Workspace(frozen)
        self.assertEqual(w.table('evaluations').rows[0]['evaluation_id'],row['id'])
        with self.assertRaisesRegex(InputError,'original sources'):w.record_evaluation(left)
        # Authored old snapshot, not a production migration: missing tables must
        # show unavailable rather than breaking every compiled Workspace query.
        with closing(sqlite3.connect(frozen)) as c:
            c.execute('DROP TABLE rl_evaluations')
            c.commit()
        self.assertFalse(w.table('evaluations')['available'])
        self.assertEqual(len(w.rollouts().rows),1)
        with self.store.connect() as c:c.execute('DROP TABLE evaluation_receipts')
        live=Workspace(self.db)
        self.assertFalse(live.table('evaluations')['available'])
        self.assertEqual(live.evaluations(run['id'])['receipts'],[])


if __name__ == '__main__':unittest.main()
