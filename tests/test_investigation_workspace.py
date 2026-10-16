import json
from pathlib import Path
import tempfile
import unittest

from rilldex import chat_document
from tracker.adapters import normalize
from tracker.store import Store
from tracker.schema import InputError
from tracker import monitoring as m, investigation_workspace as workspace, question_bundles
from tracker import failure_investigations, investigation_followups, training_lineage, analysis_metrics
from tracker.workspace_analysis import Workspace


class InvestigationWorkspaceTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.store=Store(Path(tmp.name)/'workspace.sqlite');self.serial=0
        self.success=m.create(self.store,dict(name='Task success',kind='metric',metric='recorded_success',observer='source'))
        self.reward=m.create(self.store,dict(name='Reward',kind='metric',metric='recorded_reward',observer='source'))

    def add(self,step,success=True,**metadata):
        self.serial+=1
        context=dict(experiment='run',environment='terminal',task_id='same-task',split='train',training_step=step,
                     training_clock='policy',training_step_basis='generation',**metadata)
        doc=chat_document([dict(role='assistant',content='Attempt '+str(self.serial))],metadata=context,success=success)
        run=normalize(doc)[0];self.store.add([run]);return run

    def capture(self,**kwargs):
        return workspace.save(self.store,dict(experiment='run',baseline=[0,0],current=[1,1],**kwargs))

    def test_late_results_annotations_and_events_do_not_rewrite_original(self):
        a=self.add(0);b=self.add(1,False);m.sync(self.store);old=self.capture()
        self.add(1,True);m.sync(self.store)
        event=workspace.annotate(self.store,dict(experiment='run',kind='sampling',title='Sampling support changed',detail='Recorded configuration change',step=1,clock='policy',basis='generation',investigation_id=old['id']))
        new=self.capture(parent_id=old['id'])
        self.assertEqual(failure_investigations.read(self.store,old['id']),old)
        self.assertEqual(len(old['snapshot']['population']['current']),1)
        self.assertEqual(len(new['snapshot']['population']['current']),2)
        self.assertEqual(old['snapshot']['history'],[])
        self.assertEqual(new['snapshot']['history'][0]['id'],event['id'])
        panel=next(p for p in new['snapshot']['panels'] if p['monitor']['id']==self.success['id'])
        self.assertEqual(panel['cohorts'][0]['current']['value'],.5)

    def test_shared_scope_is_not_first_monitor_population(self):
        self.add(0);self.add(1)
        scoped=m.create(self.store,dict(name='Different environment',kind='metric',metric='actions',observer='source',population={'environment':'browser'}))
        m.sync(self.store);result=self.capture(monitor_ids=[scoped['id'],self.success['id']])['snapshot']
        self.assertEqual(result['panels'][0]['population']['selected'],0)
        self.assertEqual(result['training_lineage']['windows']['current']['source_rollouts'],1)
        self.assertEqual(len(result['source_rows']),2)
        self.assertEqual(len(result['panels'][1]['cohorts'][0]['points']['current']),1)

    def test_missing_measurements_are_not_failures_and_audits_not_assumed(self):
        self.add(0);m.sync(self.store);self.add(1,False)
        panel=next(p for p in self.capture()['snapshot']['panels'] if p['monitor']['id']==self.success['id'])
        self.assertIsNone(panel['cohorts'][0]['current']['value'])
        self.assertEqual(panel['cohorts'][0]['current']['missing'],1)
        self.assertEqual(panel['reliability']['audits'],[])
        self.assertTrue(any(r['code']=='current_unmeasured' for r in panel['review']))

    def test_learner_steps_are_joined_by_exact_sample_not_step_number(self):
        ids=[]
        for step in [0,1,100]:
            row=self.store.ingest(dict(producer='actor',rollout_id=str(step),revision=0,state='complete',
                document=chat_document([dict(role='assistant',content='Source '+str(step))],success=True),
                metadata=dict(experiment='run',training_step=step,training_step_basis='generation',training_clock='policy')))
            ids.append(row['id'])
            training_lineage.receive(self.store,dict(schema='training-records/1',producer='learner',experiment='run',records=[
                dict(id='sample'+str(step),revision=0,kind='sample',sample={'producer':'actor','rollout_id':str(step)},data={'split':'train','step':step,'step_basis':'generation'},evidence={'source_revision':0,'basis':'producer source'}),
                dict(id='use'+str(step),revision=0,kind='use',sample={'producer':'actor','rollout_id':str(step)},data={'stage':'optimizer_step_completed','learner_step':700+step,'batch_id':'batch'+str(step),'model_tokens':10,'loss_tokens':8},evidence={'basis':'learner receipt'})]))
        m.sync(self.store);d=self.capture()['snapshot']['training_lineage']['windows']
        self.assertEqual([r['run_id'] for r in d['current']['rollouts']],[ids[1]])
        self.assertEqual(d['current']['stages']['optimizer']['member_rollouts'],1)
        records=d['current']['rollouts'][0]['samples'][0]['records']
        self.assertEqual(next(r for r in records if r['kind']=='use')['data']['learner_step'],701)

    def test_question_activation_skips_unsupported_semantics_and_attaches_custom(self):
        result=question_bundles.activate(self.store,{'question_id':'recovery'})
        self.assertEqual(len(result['skipped']),2)
        self.assertGreaterEqual(len(result['monitor_ids']),2)
        ws=Workspace(self.store.path,experiment='run',observer='source')
        custom=ws.monitor('Independent evaluator',version='1',description='User-defined independent check')
        # The SDK exposes its registered immutable monitor identity.
        mid=next(m['id'] for m in m.definitions(self.store) if m['name']=='Independent evaluator')
        question_bundles.bind(self.store,{'question_id':'reward-outcomes','monitor_id':mid})
        q=next(q for q in question_bundles.listing(self.store)['questions'] if q['id']=='reward-outcomes')
        self.assertTrue(any(v['id']==mid and v['kind']=='custom' for v in q['monitors']))

    def test_followup_keeps_evidence_and_sdk_capture(self):
        self.add(0);self.add(1);m.sync(self.store)
        ws=Workspace(self.store.path,experiment='run')
        d=ws.investigate_interval(baseline=[0,0],current=[1,1])
        revised=investigation_followups.save(self.store,dict(parent_id=d['id'],action='plan',check=dict(title='Fixed tasks',hypothesis='Task mix moved',procedure='Compare held-out tasks',expected_result='Outcome difference persists')))
        self.assertEqual(revised['snapshot'],d['snapshot'])
        self.assertEqual(len(revised['follow_up']['checks']),1)

    def test_custom_code_results_use_same_pinned_panels(self):
        self.add(0);self.add(1,False)
        custom=Workspace(self.store.path,experiment='run',observer='source').monitor(
            'Independent outcome control',version='authored/1',description='Authored test, not a real independent grader',
            unit='fraction',aggregation='opportunity_ratio')
        result=custom.run(lambda ctx:dict(numerator=int(ctx.run['outcome']['verified_success']),denominator=1,
            feedback={'severity':'info','summary':'Authored outcome control','next_check':'Inspect evaluator independence.'}))
        self.assertEqual(result['published'],2)
        question_bundles.bind(self.store,dict(question_id='reward-outcomes',monitor_id=custom.id))
        saved=self.capture(monitor_ids=[custom.id]);panel=saved['snapshot']['panels'][0]
        self.assertEqual(panel['cohorts'][0]['delta'],-1)
        self.assertEqual(panel['reliability']['definition_version'],'authored/1')
        self.assertEqual(len(panel['reliability']['measurement_ids']),2)
        self.add(1,True);custom.run(lambda ctx:dict(numerator=1,denominator=1))
        self.assertEqual(failure_investigations.read(self.store,saved['id']),saved)

    def test_score_comparison_does_not_pool_different_sampling_definitions(self):
        def sample(identifier):
            return dict(producer='actor',split='train',stage_membership=dict(generated='member',admitted='member',optimizer='member'),
                records=[dict(kind='score',record_producer='grader',data=dict(component='reward',definition='v1',status='scored',value=1))])
        lineage={'windows':{'current':{'rollouts':[dict(run_id=k,samples=[sample(k)]) for k in ('a','b')]}}}
        sources=[dict(id=k,metadata=dict(training_clock='policy',training_step_basis='generation',sampling=policy))
                 for k,policy in [('a','top-p'),('b','full-support')]]
        groups=workspace.learning_context(lineage,sources)['windows']['current']['scores']
        self.assertEqual(len(groups),2)
        self.assertEqual({g['context']['source_configuration']['sampling'] for g in groups},{'top-p','full-support'})

    def test_audit_summary_only_includes_exact_measurement_receipts(self):
        from test_measurement_reviews import MeasurementReviewTests
        from tracker import measurement_reviews as review
        fixture=MeasurementReviewTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        sample=review.create(fixture.store,fixture.request);raw=review.load(fixture.store,sample['id'])
        row=next(r for r in raw['frame'] if r['prediction'] is True)
        review.receive(fixture.store,fixture.label(sample,row['id'],'taken'))
        matched=workspace.audit_summary(fixture.store,fixture.monitor['id'],{row['measurement_id']})
        self.assertEqual(matched[0]['agreement'],1)
        self.assertEqual(matched[0]['reviewed'],1)
        self.assertEqual(workspace.audit_summary(fixture.store,fixture.monitor['id'],{'different-receipt'}),[])

    def test_invalid_scope_windows_and_history_links(self):
        for payload in [dict(experiment='run',baseline=[0,1],current=[1,2]),dict(experiment='',baseline=[0,0],current=[1,1]),dict(experiment='run',baseline=[0,0],current=[1,1],monitor_ids=['missing'])]:
            with self.assertRaises((InputError,KeyError)):workspace.save(self.store,payload)
        with self.assertRaises(InputError):workspace.annotate(self.store,dict(experiment='run',kind='restart',title='Restart',detail='Restored state',step=1,clock='',basis='generation'))

    def test_repeated_and_unresolved_windows_keep_original_witnesses(self):
        rows=[dict(id='a',criterion_id='criterion',failure_action_id='e1',value=False,status='not_recovered_in_window',event_ids=['e1','e2'],feedback_reference_edge_ids=[],attempts=[{'status':'failed'}]*3),
              dict(id='b',criterion_id='criterion',failure_action_id='e3',value=None,status='unknown',event_ids=['e3'],feedback_reference_edge_ids=[],attempts=[])]
        output=dict(records=rows,coverage={})
        repeated=analysis_metrics.measure(output,analysis_metrics.catalog()['repeated_failed_checks'])
        unknown=analysis_metrics.measure(output,analysis_metrics.catalog()['incomplete_recovery_followup'])
        self.assertEqual((repeated['value'],unknown['value']),(1,1))
        self.assertEqual(repeated['cases'][0]['record'],rows[0])
        self.assertEqual(unknown['cases'][0]['record'],rows[1])
        self.assertEqual(unknown['opportunities'],2)

    def test_32_step_arrival_replay_exposes_mix_without_false_causal_claim(self):
        # Controlled workflow replay, not evidence of classifier accuracy or RL convergence.
        for step in range(32):
            for i in range(8):
                self.serial+=1
                self.add(step,i<6 if step<16 else i<2)
        m.sync(self.store)
        before=workspace.save(self.store,dict(experiment='run',baseline=[0,15],current=[16,31],monitor_ids=[self.success['id']]))
        self.assertEqual(before['snapshot']['panels'][0]['cohorts'][0]['delta'],-.5)
        for step in range(16,32):
            for _ in range(16):self.add(step,True)
        m.sync(self.store)
        after=workspace.save(self.store,{**before['controls'],'parent_id':before['id']})
        self.assertEqual(len(before['snapshot']['population']['current']),128)
        self.assertEqual(len(after['snapshot']['population']['current']),384)
        self.assertEqual(after['snapshot']['panels'][0]['cohorts'][0]['delta'],0)
        self.assertEqual(failure_investigations.read(self.store,before['id'])['snapshot'],before['snapshot'])


if __name__=='__main__':unittest.main()
