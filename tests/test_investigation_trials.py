"""Executable, authored workflow controls; not a real trainer benchmark."""
from copy import deepcopy
import json
from pathlib import Path
import random
import tempfile
import unittest

from rilldex import TrialStudy
from tracker import failure_investigations as investigations, investigation_followups as follow
from tracker import investigation_trials as trials
from tracker import run_records
from tracker.adapters import normalize
from tracker.schema import InputError
from tracker.store import Store
from test_tracker import harbor


def setup(store):
    raw = harbor()
    for step in range(4, 100):
        raw['steps'].append(dict(step_id=step, source='agent', message=f'Authored debugging attempt {step}: inspect dependency and rerun parser.'))
    raw['steps'].append(dict(step_id=100, source='agent', message='FUTURE_ANSWER: parser needs ISO mode'))
    run = normalize(raw, 'harbor', dict(experiment='trial-workflow-controls', task_id='parser', checkpoint='label-only', training_step=32))[0]
    run['outcome'] = dict(recorded_reward=1, verified_success=False)
    store.add([run])
    snapshot = investigations.snapshot(store, run=run['id'])
    doc = investigations.save(store, dict(controls=snapshot['controls'], snapshot_id=snapshot['snapshot_id'],
        title='Debug a rewarded but failing parser rollout', hypothesis='Context or sampling may explain the failure', x='source:actions', y='source:recorded_reward'))
    return doc, run


def design(run, mode='replay'):
    return dict(mode=mode, run_id=run['id'], through_event_id=run['events'][20]['id'],
        configuration=dict(values=dict(temperature=.7, learning_rate=.01, sync_interval=64, grader='substring')),
        checkpoint=dict(reference='', available_state=[]), variants=[dict(name='Context correction', parameters={}, context_append='Preserve ISO support.')],
        seeds=list(range(8)), budget=dict(max_trials=32, max_steps=64, max_tokens=32768),
        measure=dict(key='success', label='Independent parser checks', unit='0–1'))


def plan(store, doc, raw):
    return follow.save(store, dict(parent_id=doc['id'], action='plan', check=dict(title='Context and sampling controls',
        hypothesis='The failure may be caused by lost context', procedure='Run the pinned prefix with paired seeds',
        expected_result='Context correction improves independent checks', trial=raw)))


def applied(job, **changes):
    return dict(configuration=deepcopy(job['configuration']), context_append=job['context_append'], seed=job['seed'],
        checkpoint_reference=job['checkpoint']['reference'], restored_state=job['checkpoint']['available_state'], **changes)


class TrialTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name)/'study.sqlite')
        self.doc, self.run = setup(self.store)

    def study(self, raw=None):
        doc = plan(self.store, self.doc, raw or design(self.run)); check = doc['follow_up']['checks'][0]
        handoff = trials.manifest(self.store, doc['id'], check['id'])
        return doc, check, TrialStudy(handoff)

    def execute(self, study, callback, name='results.json'):
        return study.run(callback, output=Path(self.tmp.name)/name)

    def attach(self, doc, check, result):
        return follow.save(self.store, dict(parent_id=doc['id'], action='trial_results', check=dict(id=check['id'],
            results=[{k:v for k,v in r.items() if k!='id'} for r in result['results']])))

    def test_long_prefix_is_pinned_and_future_answer_is_not_sent(self):
        doc, check, study = self.study()
        self.assertGreater(len(self.run['events']), 100)
        self.assertEqual(len(study.manifest['prefix']), 21)
        self.assertNotIn('FUTURE_ANSWER', json.dumps(study.manifest))
        self.assertNotIn('outcome', study.manifest)
        self.assertNotIn('raw', study.manifest)
        mutated = deepcopy(study.manifest); mutated['prefix'].append(dict(text='leak'))
        with self.assertRaisesRegex(InputError, 'prefix changed'): TrialStudy(mutated)
        self.assertNotIn('follow_up', investigations.read(self.store, self.doc['id']))
        self.assertEqual(doc['snapshot'], self.doc['snapshot'])

    def test_context_vs_sampling_under_stochastic_uncertainty(self):
        raw=design(self.run)
        raw['variants'].append(dict(name='Lower temperature',parameters=dict(temperature=.2),context_append=''))
        doc,check,study=self.study(raw)
        def runner(job):
            # Authored noisy checks, same seed across arms; a sampling change
            # alone cannot recover omitted task instructions in this simulator.
            rng=random.Random(job['seed']); correct='ISO' in job['context_append']
            checks=[rng.random() < (.85 if correct else .25) for _ in range(64)]
            return dict(status='completed',metrics=dict(success=sum(checks)/len(checks)),applied=applied(job))
        result=self.execute(study,runner)
        contrasts=result['comparison']['contrasts']
        self.assertGreater(contrasts[0]['mean_difference'], .4)
        self.assertEqual(contrasts[1]['mean_difference'], 0)
        self.assertEqual(contrasts[0]['paired'],8)
        saved=self.attach(doc,check,result)
        self.assertEqual(saved['follow_up']['checks'][0]['trial_comparison'],result['comparison'])
        self.assertEqual(saved['snapshot'],doc['snapshot'])
        self.assertEqual(self.attach(saved,check,result),saved)

    def test_reward_rescore_changes_grader_without_generating_a_policy_rollout(self):
        raw=design(self.run,'evaluate');raw['through_event_id']=self.run['events'][-1]['id']
        raw['variants']=[dict(name='Independent checks',parameters=dict(grader='parser-tests'))]
        _,_,study=self.study(raw);calls=[]
        def rescore(job):
            self.assertEqual(job['mode'],'evaluate');self.assertEqual(len(job['prefix']),len(self.run['events']))
            calls.append(job['arm'])
            return dict(status='completed',metrics=dict(success=int(job['configuration']['grader']=='substring')),applied=applied(job))
        result=self.execute(study,rescore)
        self.assertEqual(result['comparison']['contrasts'][0]['mean_difference'],-1)
        self.assertEqual(len(calls),16)

    def test_resume_checkpoint_and_test_learning_rate_vs_sync(self):
        raw=design(self.run,'train');raw['checkpoint']=dict(reference='checkpoints/step_24',available_state=['model','optimizer','scheduler','rng','data'])
        raw['variants']=[dict(name='Lower LR',parameters=dict(learning_rate=.001)),dict(name='Faster sync',parameters=dict(sync_interval=8))]
        _,_,study=self.study(raw)
        def train(job):
            state=.7;cfg=job['configuration'];rng=random.Random(job['seed'])
            for _ in range(job['budget']['max_steps']):
                state += .001-rng.random()*.0002-(.008 if cfg['sync_interval']>32 else 0)
            return dict(status='completed',metrics=dict(success=state),applied=applied(job))
        result=self.execute(study,train)
        self.assertAlmostEqual(result['comparison']['contrasts'][0]['mean_difference'],0)
        self.assertGreater(result['comparison']['contrasts'][1]['mean_difference'],.5)

    def test_missing_shards_and_changed_settings_are_visible_not_scored_as_failure(self):
        raw=design(self.run,'train');raw['checkpoint']=dict(reference='step_24',available_state=['model'])
        raw['variants']=[dict(name='Lower LR',parameters=dict(learning_rate=.001))]
        _,_,study=self.study(raw)
        def runner(job):
            report=applied(job)
            if job['arm']!='Reference':report['configuration']['learning_rate']=.01
            return dict(status='completed',metrics=dict(success=.9),applied=report)
        result=self.execute(study,runner)
        self.assertIsNone(result['comparison']['contrasts'][0]['mean_difference'])
        self.assertEqual(result['comparison']['rows'][0]['value'],.9)
        self.assertTrue(any('Unrestored state' in x for x in result['comparison']['rows'][0]['issues']))
        self.assertIn('Different configuration',result['comparison']['rows'][1]['issues'])

    def test_intentional_checkpoint_branch_reset_is_distinct_from_missing_state(self):
        raw=design(self.run,'train')
        raw['checkpoint']=dict(reference='checkpoint.zip',available_state=['model','optimizer','scheduler'],
                               reset_state=['rng','data','environment'])
        raw['variants']=[dict(name='Lower LR',parameters=dict(learning_rate=.001))]
        _,_,study=self.study(raw)
        def runner(job):
            report=applied(job,reset_state=['rng','data','environment'])
            if job['seed']==0:report['reset_state']=[]  # silently ignoring the planned reset
            return dict(status='completed',metrics=dict(success=.5),applied=report)
        result=self.execute(study,runner)
        self.assertEqual(result['comparison']['contrasts'][0]['paired'],7)
        self.assertIn('Different restarted state',result['comparison']['rows'][0]['issues'])
        self.assertEqual(result['comparison']['rows'][2]['issues'],[])
        conflict=deepcopy(raw);conflict['checkpoint']['reset_state'].append('optimizer')
        with self.assertRaisesRegex(InputError,'restored and restarted'):self.study(conflict)
        conflict=deepcopy(raw);conflict['checkpoint']['reset_state'].append('model');conflict['checkpoint']['available_state'].remove('model')
        with self.assertRaisesRegex(InputError,'must restore the model'):self.study(conflict)
        check=dict(trial=study.manifest['trial']);job=study.manifest['jobs'][0]
        with self.assertRaisesRegex(InputError,'both restored and restarted'):
            trials.receipt(None,check,dict(job_id=job['id'],status='completed',applied=applied(job,reset_state=['optimizer'])))

    def test_partial_execution_can_restart_without_repeating_completed_jobs(self):
        _,_,study=self.study();calls=[]
        def interrupted(job):
            if len(calls)==3:raise KeyboardInterrupt()
            calls.append(job['id'])
            return dict(status='completed',metrics=dict(success=1),applied=applied(job))
        with self.assertRaises(KeyboardInterrupt):self.execute(study,interrupted)
        first=json.loads(Path(self.tmp.name,'results.json').read_text(encoding='utf-8'))
        self.assertEqual(len(first['results']),3)
        self.assertEqual(sum(r['status']=='pending' for r in first['comparison']['rows']),13)
        def resumed(job):
            self.assertNotIn(job['id'],calls);calls.append(job['id'])
            return dict(status='completed',metrics=dict(success=1),applied=applied(job))
        result=self.execute(study,resumed)
        self.assertEqual(len(calls),16)
        self.assertEqual(result['comparison']['contrasts'][0]['paired'],8)
        self.execute(study,lambda j:self.fail('Completed jobs ran again'))

    def test_error_unknown_and_failed_outcome_have_separate_meaning(self):
        _,_,study=self.study()
        def runner(job):
            if job['seed']==0:raise OSError('Checkpoint shard unavailable')
            if job['seed']==1:return dict(status='incomplete',note='Waiting for verifier')
            if job['seed']==2:return dict(status='completed',metrics={})
            return dict(status='completed',metrics=dict(success=0),applied=applied(job))
        result=self.execute(study,runner)
        self.assertEqual(result['comparison']['contrasts'][0]['paired'],5)
        self.assertEqual(result['comparison']['contrasts'][0]['mean_difference'],0)
        self.assertEqual({r['status'] for r in result['comparison']['rows']},{'error','incomplete','completed'})

    def test_wrong_source_budget_and_incomplete_rescore_are_rejected(self):
        cases=[dict(run_id='unrelated'),dict(seeds=[0,0]),dict(budget=dict(max_trials=1,max_steps=64,max_tokens=128)),dict(mode='evaluate')]
        for change in cases:
            with self.subTest(change=change),self.assertRaises(InputError):self.study(dict(design(self.run),**change))

    def test_config_overlay_and_null_are_unambiguous(self):
        self.assertEqual(trials.overlay(dict(a=dict(x=1,y=2),b=[1]),dict(a=dict(x=None),b=[2])),dict(a=dict(x=None,y=2),b=[2]))

    def test_source_options_resolve_configuration_explicitly(self):
        # Newer run settings must not silently become the settings at an older
        # rollout boundary. The form returns snapshots and requires a pick.
        data=trials.options(self.store,self.doc['id'])
        self.assertEqual(data['selected'],self.run['id'])
        self.assertEqual(len(data['events']),len(self.run['events']))
        self.assertEqual(data['configurations'],[])
        for session,temperature in [('first',.7),('restart',.2)]:
            run_records.receive(self.store,dict(schema='run-records/1',producer='worker',experiment='trial-workflow-controls',records=[dict(
                id=session,session=session,kind='manifest',observed_at='2026-10-23T00:00:00Z',
                payload=dict(name='trial-workflow-controls',project='study',config=dict(temperature=temperature),runtime={}))]))
        choices=trials.options(self.store,self.doc['id'])['configurations']
        raw=design(self.run);raw['configuration']=dict(source_id=next(c['id'] for c in choices if c['session']=='first'))
        _,check,_=self.study(raw)
        self.assertEqual(check['trial']['configuration']['values'],dict(temperature=.7))
        self.assertEqual(check['trial']['configuration']['reference']['session'],'first')
        with self.assertRaisesRegex(InputError,'saved comparison'):trials.options(self.store,self.doc['id'],'other')

    def test_code_only_return_and_retry_keep_prior_failed_receipt(self):
        doc,check,study=self.study()
        result=self.execute(study,lambda job:dict(status='blocked',note='Environment snapshot unavailable'))
        self.execute(study,lambda job:self.fail('Blocked jobs need explicit retry'))
        result=study.run(lambda job:dict(status='completed',metrics=dict(success=1),applied=applied(job)),
            output=Path(self.tmp.name)/'results.json',retry_failed=True)
        self.assertEqual(len(result['results']),32)
        self.assertEqual(result['comparison']['contrasts'][0]['paired'],8)
        saved=study.record_results(Path(self.tmp.name)/'study.sqlite',result)
        self.assertEqual(len(saved['follow_up']['checks'][0]['trial_results']),32)
        self.assertNotIn('trial_results',investigations.read(self.store,doc['id'])['follow_up']['checks'][0])

    def test_trial_id_and_result_identity_cannot_be_substituted(self):
        _,check,study=self.study();changed=deepcopy(study.manifest);changed['trial']['seeds']=[9]
        with self.assertRaisesRegex(InputError,'design changed'):TrialStudy(changed)
        with self.assertRaisesRegex(InputError,'planned trial'):trials.receipt(self.store,check,dict(job_id='other',status='completed'))

    def test_typed_settings_and_extreme_numeric_results_remain_distinct(self):
        raw=design(self.run);raw['configuration']['values']['enabled']=True
        _,_,study=self.study(raw)
        def runner(job):
            report=applied(job)
            if job['seed']==0:report['configuration']['enabled']=1
            return dict(status='completed',metrics=dict(success=1e308 if job['arm']=='Reference' else -1e308),applied=report)
        result=self.execute(study,runner)
        self.assertIn('Different configuration',result['comparison']['rows'][0]['issues'])
        contrast=result['comparison']['contrasts'][0]
        self.assertIsNone(contrast['mean_difference'])
        self.assertEqual(contrast['unrepresentable_differences'],7)
        json.dumps(result,allow_nan=False)

    def test_prepare_after_notes_keeps_original_check(self):
        doc=follow.save(self.store,dict(parent_id=self.doc['id'],action='plan',check=dict(title='Check queue composition',hypothesis='Short tasks arrived earlier',procedure='Wait for the same generated cohort',expected_result='Late completions alter the outcome')))
        check=doc['follow_up']['checks'][0]
        saved=follow.save(self.store,dict(parent_id=doc['id'],action='trial',check=dict(id=check['id'],trial=design(self.run))))
        self.assertEqual(saved['follow_up']['checks'][0]['id'],check['id'])
        self.assertNotIn('trial',investigations.read(self.store,doc['id'])['follow_up']['checks'][0])
        with self.assertRaisesRegex(InputError,'pinned'):follow.save(self.store,dict(parent_id=saved['id'],action='trial',check=dict(id=check['id'],trial=design(self.run))))

    def test_early_arrivals_remain_incomplete_instead_of_triggering_a_parameter_conclusion(self):
        _,_,study=self.study();calls=0
        def queue(job):
            nonlocal calls
            calls+=1
            if calls==5:raise KeyboardInterrupt()
            return dict(status='completed',metrics=dict(success=0),applied=applied(job))
        with self.assertRaises(KeyboardInterrupt):self.execute(study,queue)
        result=json.loads(Path(self.tmp.name,'results.json').read_text(encoding='utf-8'))
        self.assertEqual(result['comparison']['contrasts'][0]['paired'],2)
        self.assertEqual(result['comparison']['contrasts'][0]['planned'],8)
        self.assertEqual(sum(r['status']=='pending' for r in result['comparison']['rows']),12)


if __name__=='__main__':unittest.main()
