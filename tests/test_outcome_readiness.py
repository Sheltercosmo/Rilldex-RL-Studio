"""Readiness must not turn fast arrivals or failed capture into task failure."""
import tempfile
import unittest
from pathlib import Path

from tracker import generation_cohorts as cohorts, training_health
from tracker.portable import chat_document
from tracker.store import Store


class OutcomeReadinessTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.store=Store(Path(tmp.name)/'study.sqlite')

    def declare(self, revision=0, sealed=True, identifier='batch'):
        members=[dict(producer='worker',rollout_id=str(i),generation_state='admitted' if i<3 else 'cancelled',
                      context=dict(task_id='short' if i<2 else 'long')) for i in range(4)]
        return cohorts.receive(self.store,dict(schema=cohorts.VERSION,producer='scheduler',experiment='x',cohorts=[
            dict(id=identifier,revision=revision,label='Generation 1',coordinate=dict(clock='generation',basis='batch',index=1),
                 context=dict(environment='terminal'),sealed=sealed,members=members,evidence='Fixed scheduler fixture')]))

    def deliver(self, i, success, *, revision=0, state='complete', environment='terminal'):
        return self.store.ingest(dict(producer='worker',rollout_id=str(i),revision=revision,state=state,
            document=chat_document([dict(role='user',content='Repair the object'),dict(role='assistant',content='Checked')],
                metadata=dict(experiment='x',environment=environment,task_id='short' if i<2 else 'long',
                    training_clock='generation',training_step_basis='batch',training_step=1),success=success)))

    def read(self):
        return cohorts.snapshot(self.store,experiment='x')['cohorts'][0]

    def test_fast_arrivals_are_provisional_and_reveal_changed_task_representation(self):
        self.declare();self.deliver(0,False);self.deliver(1,True)
        r=self.read();s=r['outcome_support']
        self.assertEqual((s['observed_rate'],s['coverage'],s['lower'],s['upper']),(.5,.5,.25,.75))
        self.assertFalse(s['complete'])
        task=next(x for x in r['outcome_selection'] if x['field']=='task_id')
        self.assertEqual(task['representation_distance'],.5)
        long=next(x for x in task['groups'] if x['value']=='long')
        self.assertEqual((long['known'],long['declared'],long['success_rate']),(0,2,None))
        env=next(x for x in r['outcome_selection'] if x['field']=='environment')
        self.assertEqual(env['groups'][0]['value'],'terminal')

    def test_late_results_change_same_coordinate_without_changing_saved_payload(self):
        self.declare();self.deliver(0,False)
        before=cohorts.snapshot(self.store,experiment='x')
        self.deliver(1,True);self.deliver(2,True);self.deliver(3,True)
        after=cohorts.snapshot(self.store,experiment='x')
        s=after['cohorts'][0]['outcome_support']
        self.assertEqual((s['lower'],s['upper'],s['observed_rate']),(.75,.75,.75))
        self.assertTrue(s['complete'])
        self.assertEqual(before['cohorts'][0]['outcome_support']['known'],1)
        self.assertNotEqual(before['snapshot_id'],after['snapshot_id'])
        self.assertEqual(before['cohorts'][0]['coordinate'],after['cohorts'][0]['coordinate'])

    def test_failed_or_in_progress_capture_does_not_supply_final_outcome(self):
        self.declare();self.deliver(0,False,state='failed');self.deliver(1,True,state='in_progress')
        s=self.read()['outcome_support']
        self.assertEqual((s['known'],s['unknown'],s['lower'],s['upper']),(0,4,0,1))
        self.assertIsNone(s['observed_rate'])

    def test_context_conflict_remains_unknown(self):
        self.declare();self.deliver(0,True,environment='browser')
        r=self.read();self.assertEqual(r['source_conflicts'],1)
        self.assertEqual(r['outcome_support']['known'],0)

    def test_open_membership_has_no_final_population_bounds(self):
        self.declare(sealed=False);self.deliver(0,True)
        s=self.read()['outcome_support']
        self.assertEqual(s['observed_rate'],1)
        self.assertIsNone(s['lower']);self.assertIsNone(s['upper']);self.assertFalse(s['complete'])

    def test_overlapping_cohorts_remain_separate_not_a_pooled_rate(self):
        self.declare();self.declare(identifier='retry-window');self.deliver(0,True)
        d=cohorts.snapshot(self.store,experiment='x')
        self.assertEqual(d['distinct_declared_rollouts'],4)
        self.assertEqual(d['overlapping_members'],4)
        self.assertNotIn('outcome_support',d)
        self.assertTrue(all(r['outcome_support']['known']==1 for r in d['cohorts']))

    def test_health_exposes_scheduler_evidence_without_training_facts_and_updates_identity(self):
        self.declare();before=training_health.snapshot(self.store,experiment='x')
        self.deliver(0,True);after=training_health.snapshot(self.store,experiment='x')
        self.assertEqual(before['cohorts'],[])
        self.assertEqual(after['declared_populations']['cohorts'][0]['outcome_support']['known'],1)
        self.assertNotEqual(before['snapshot_id'],after['snapshot_id'])


if __name__=='__main__':unittest.main()
