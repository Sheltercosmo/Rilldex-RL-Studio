import copy
from pathlib import Path
import tempfile
import unittest

from tracker import attempt_chains as ac, training_health, training_lineage
from tracker.schema import InputError
from tracker.store import Store, ReviewConflict


def declaration(chain, position, *, budget=2, **extra):
    return dict(schema=ac.LINEAGE, producer='controller', chain_id=chain,
                attempt_id=f'{chain}/{position}', position=position, budget=budget,
                previous_attempt_id=f'{chain}/{position-1}' if position > 1 else None,
                protocol='failure-feedback-reset/1', context='failure_feedback' if position > 1 else 'initial',
                reset='original_state', **extra)


def record(kind, sample, data, revision=0, identifier=None):
    return dict(id=identifier or kind+'/'+sample, revision=revision, kind=kind,
                sample=dict(producer='worker', rollout_id=sample),
                evidence=dict(basis='authored contract control'), data=data)


def attempt(chain, position, result, *, sample=None, budget=2, step=0, reward=None):
    sample = sample or f'{chain}/{position}'
    a = record('sample', sample, dict(split='train', task_id='task', step=step,
                step_basis='generation', attempt=declaration(chain, position, budget=budget)))
    s = record('score', sample, dict(component='verifier', definition='criterion/1', status='scored',
                value=reward if reward is not None else int(result == 'passed'),
                attempt_outcome=dict(schema=ac.OUTCOME, attempt_id=f'{chain}/{position}', result=result)))
    return [a, s]


class AttemptChainTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.store = Store(Path(tmp.name)/'attempts.sqlite')

    def add(self, *rows, version='training-records/1', producer='worker'):
        rows = copy.deepcopy(rows)
        if version == 'training-records/2':
            for row in rows: row['sample']['id'] = row['sample'].pop('rollout_id')
        packet = dict(schema=version, producer=producer, experiment='test', records=list(rows))
        return training_lineage.receive(self.store, packet)

    def view(self):
        return training_health.snapshot(self.store)['cohorts'][0]['attempt_chains'][0]

    def test_recovered_failed_stopped_and_missing_paths(self):
        for chain, results in [('early', ['passed']), ('recover', ['failed','passed']),
                               ('fail', ['failed','failed']), ('pending', ['failed'])]:
            for pos, result in enumerate(results,1): self.add(*attempt(chain,pos,result))
        v = self.view()
        self.assertEqual(v['attempts'],6)  # No fictitious slots for early or pending.
        self.assertEqual(v['first_success']['value'],.25)
        self.assertEqual(v['first_retry_success'],dict(value=.5,numerator=1,denominator=2,unknown=1,opportunities=3,lower=1/3,upper=2/3))
        self.assertEqual(v['within_budget_success'],dict(value=2/3,numerator=2,denominator=3,unknown=1,opportunities=4,lower=.5,upper=.75))
        self.assertEqual(v['by_budget'][0]['value'],.25)

    def test_scores_never_become_outcomes_and_late_records_update(self):
        a,s = attempt('a',1,'failed',reward=100)
        del s['data']['attempt_outcome']; self.add(a,s)
        self.assertIsNone(self.view()['first_success']['value'])
        s['revision']=1; s['data']['attempt_outcome']=dict(schema=ac.OUTCOME,attempt_id='a/1',result='failed')
        self.add(s)
        self.assertEqual(self.view()['first_success']['value'],0)
        self.assertEqual(self.view()['within_budget_success']['unknown'],1)
        self.add(*attempt('a',2,'passed',reward=-100))
        self.assertEqual(self.view()['within_budget_success']['value'],1)

    def test_shared_attempt_samples_deduplicate_in_both_transport_versions(self):
        for version in ['training-records/1','training-records/2']:
            with self.subTest(version=version):
                # New store for the two independent identity namespaces.
                self.store=Store(self.store.path.parent/(version[-1]+'.sqlite'))
                for sample in ['sample-a','sample-b']:
                    self.add(*attempt('a',1,'passed',sample=sample),version=version)
                self.assertEqual(self.view()['initial_attempts'],1)
                self.assertEqual(self.view()['attempts'],1)
                self.assertEqual(self.view()['first_success']['denominator'],1)

    def test_conflicting_outcomes_and_wrong_identity_do_not_pass(self):
        self.add(*attempt('a',1,'passed',sample='a'))
        self.add(*attempt('a',1,'failed',sample='b'))
        self.assertEqual(self.view()['cases'][0]['attempts'][0]['reason'],'conflicting_outcomes')
        self.assertIsNone(self.view()['first_success']['value'])
        bad=attempt('b',1,'passed');bad[1]['data']['attempt_outcome']['attempt_id']='other'
        self.add(*bad)
        self.assertEqual(self.view()['first_success']['unknown'],2)

    def test_broken_parent_or_continuation_after_success_is_unresolved(self):
        self.add(*attempt('after-success',1,'passed'),*attempt('after-success',2,'passed'))
        bad=attempt('bad-parent',2,'passed');bad[0]['data']['attempt']['previous_attempt_id']='elsewhere'
        self.add(*attempt('bad-parent',1,'failed'),*bad)
        self.add(*attempt('orphan',2,'passed'))
        v=self.view()
        self.assertEqual(v['invalid_chains'],3)
        self.assertEqual(v['missing_initial'],1)
        self.assertEqual(v['within_budget_success']['unknown'],2)
        self.assertIsNone(v['first_retry_success']['value'])

    def test_root_training_coordinate_and_missing_coordinates(self):
        self.add(*attempt('a',1,'failed',step=7),*attempt('a',2,'passed',step=99))
        rows=attempt('b',1,'passed');rows[0]['data'].pop('step');rows[0]['data'].pop('step_basis')
        self.add(*rows)
        views=[v for c in training_health.snapshot(self.store)['cohorts'] for v in c['attempt_chains']]
        known=next(v for v in views if v['points'])
        self.assertEqual([p['step'] for p in known['points']],[7])
        self.assertEqual(known['points'][0]['within_budget_success']['value'],1)
        self.assertEqual(next(v for v in views if not v['points'])['missing_root_step'],1)

    def test_protocol_budget_and_verifier_definitions_never_pool(self):
        self.add(*attempt('a',1,'passed',budget=1))
        rows=attempt('b',1,'failed');rows[0]['data']['attempt']['protocol']='fresh-retry/1';self.add(*rows)
        other=copy.deepcopy(rows[1]);other['id']='other-score';other['data']['definition']='other-criterion/1'
        other['data']['attempt_outcome']['result']='passed';self.add(other)
        views=training_health.snapshot(self.store)['cohorts'][0]['attempt_chains']
        self.assertEqual(len(views),4)
        self.assertEqual({v['budget'] for v in views},{1,2})

    def test_duplicate_position_or_task_conflict_cannot_be_used(self):
        self.add(*attempt('a',1,'failed'))
        second=attempt('a',2,'passed');second[0]['data']['task_id']='different';self.add(*second)
        self.assertIn('task_identity_conflict',self.view()['cases'][0]['issues'])
        self.assertIsNone(self.view()['within_budget_success']['value'])

    def test_unknown_parent_cannot_establish_failure_condition(self):
        self.add(*attempt('a',1,'unknown'),*attempt('a',2,'passed'))
        self.assertIn('failure_trigger_not_established',self.view()['cases'][0]['issues'])
        self.assertIsNone(self.view()['within_budget_success']['value'])

    def test_same_executed_attempt_cannot_seed_multiple_chains(self):
        self.add(*attempt('a',1,'passed'))
        rows=attempt('a',1,'passed',sample='another-sample')
        rows[0]['data']['attempt']['chain_id']='b';self.add(*rows)
        v=self.view();self.assertEqual(v['invalid_chains'],2)
        self.assertTrue(all('attempt_in_multiple_chains' in c['issues'] for c in v['cases']))
        self.assertIsNone(v['first_success']['value'])

    def test_contract_rejects_malformed_and_out_of_budget_inputs(self):
        for field, value in [('position',True),('budget',0),('budget',1001),('previous_attempt_id','self'),('context','failure_feedback')]:
            rows=attempt('a',1,'passed');rows[0]['data']['attempt'][field]=value
            with self.subTest(field=field), self.assertRaises(InputError):self.add(*rows)
        rows=attempt('a',1,'passed');rows[0]['data'].pop('task_id')
        with self.assertRaises(InputError):self.add(*rows)
        rows=attempt('a',1,'passed');rows[1]['data'].update(status='error',value=None)
        with self.assertRaises(InputError):self.add(*rows)

    def test_reverse_delivery_replay_and_immutable_identity(self):
        rows=attempt('a',1,'failed')+attempt('a',2,'passed')
        self.add(*reversed(rows));before=training_health.snapshot(self.store)
        self.add(*rows);self.assertEqual(before,training_health.snapshot(self.store))
        changed=copy.deepcopy(rows[0]);changed['data']['attempt']['protocol']='changed'
        with self.assertRaises(ReviewConflict):self.add(changed)
        corrected=copy.deepcopy(rows[-1]);corrected['revision']=2;corrected['data']['attempt_outcome']['result']='failed'
        self.add(corrected);self.add(rows[-1]);self.assertEqual(self.view()['within_budget_success']['value'],0)

    def test_behavior_comparison_deduplicates_sources_and_keeps_missing(self):
        self.add(*attempt('a',1,'failed'),*attempt('a',2,'passed'))
        population=training_lineage.snapshot(self.store)
        rows=population['samples']
        for s in rows:
            s['run_id']='source-'+str(s['attempt']['position']);s['monitor_population']='included'
            s['measurement']=dict(status='available',value=s['attempt']['position']*2)
        duplicate=copy.deepcopy(rows[0]);duplicate['rollout_id']='duplicate';rows.append(duplicate)
        views=ac.project(rows,training_health.sample_ref,monitor=True)
        b=views[0]['behavior_by_position']
        self.assertEqual([g['mean_per_rollout'] for g in b],[2,4])
        self.assertEqual(b[0]['population'],2)
        self.assertEqual(b[0]['source_measured'],1)
        rows[1]['monitor_population']='excluded'
        b=ac.project(rows,training_health.sample_ref,monitor=True)[0]['behavior_by_position']
        self.assertEqual(b[1]['outside_monitor_scope'],1)
        self.assertIsNone(b[1]['mean_per_rollout'])


if __name__ == '__main__':unittest.main()
