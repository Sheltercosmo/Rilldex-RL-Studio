"""Projection consistency and native clock controls, not semantic accuracy tests."""
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from tracker import behavior_distributions as bd, graph_store as gs, work_visits, work_order
from tracker.schema import InputError, digest
from tracker.store import Store
from tests.test_parallel_work_returns import fixture, graph


class WorkDistributionOrderTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.store=Store(Path(folder.name)/'test.sqlite')

    def save(self, step=1, basis='rollout_batch', gap=False):
        run,units=fixture()
        run['metadata'].update(experiment='authored-order-control',task_id='same-task',
                               training_step=step,training_step_basis=basis)
        run['id']=digest([run['id'],step,basis,gap])[:24]
        g=graph(run,units,('A',None,'C','A') if gap else ('A','B','C','A'))
        self.store.add([run])
        with self.store.connect() as c:gs.save(c,g)
        return g

    def test_old_default_and_explicit_parallel_policy_have_distinct_receipts(self):
        g=self.save()
        old=bd.snapshot(self.store,lens='work_visits')
        new=bd.snapshot(self.store,lens='work_visits',recurrence_order=work_order.VERSION)
        self.assertEqual(old['distribution']['counts']['returned'],0)
        self.assertEqual(new['distribution']['counts']['returned'],1)
        self.assertEqual(new['points'][0]['switches'],work_visits.project(g,recurrence_order=work_order.VERSION)['metrics'])
        self.assertEqual(new['points'][0]['switches']['unknown'],2)
        self.assertNotEqual(old['analysis_receipts'][0]['plan_id'],new['analysis_receipts'][0]['plan_id'])
        self.assertNotEqual(old['snapshot_id'],new['snapshot_id'])
        for case in new['cases']:
            params=parse_qs(urlparse(case['map_url']).query)
            self.assertEqual(params['recurrence_order'],[work_order.VERSION])
            self.assertEqual(params['graph'],[g['id']])
            self.assertEqual(params['work_visit'],[case['id']])
        for case in old['cases']:
            self.assertNotIn('recurrence_order=',case['map_url'])
        with self.store.connect() as c:count=c.execute('SELECT count(*) FROM investigation_nodes').fetchone()[0]
        self.assertEqual(new,bd.snapshot(self.store,lens='work_visits',recurrence_order=work_order.VERSION))
        with self.store.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM investigation_nodes').fetchone()[0],count)
        self.assertEqual(new['inference_calls'],0)

    def test_gaps_and_cohort_windows_keep_correct_denominators(self):
        self.save(1);self.save(3,gap=True)
        out=bd.snapshot(self.store,lens='work_visits',recurrence_order=work_order.VERSION)
        self.assertEqual(len(out['points']),2)
        self.assertEqual(out['baseline']['counts']['returned'],1)
        self.assertEqual(out['current']['counts']['returned'],0)
        self.assertEqual(out['current']['counts']['interrupted'],1)
        self.assertTrue(out['comparable'])
        for window in ('baseline','current'):
            self.assertEqual(sum(out[window]['counts'].values()),out[window]['total'])
            self.assertAlmostEqual(sum(out[window]['shares'].values()),1)

    def test_source_clock_partitions_and_labels_without_assuming_optimizer_steps(self):
        for basis in ('slime_rollout_batch','optimizer_update',None):self.save(basis=basis)
        out=bd.snapshot(self.store,lens='work_visits',recurrence_order=work_order.VERSION)
        self.assertEqual(len(out['cohorts']),3)
        for cohort in out['cohorts']:
            view=bd.snapshot(self.store,lens='work_visits',cohort_id=cohort['id'])
            self.assertEqual(view['population'],1)
            basis=cohort['metadata']['training_step_basis']
            self.assertEqual(view['axis']['basis'],basis)
            if basis is None:self.assertIn('unspecified',view['axis']['label'])
            if basis=='slime_rollout_batch':self.assertEqual(view['axis']['label'],'Slime rollout batch index')

    def test_unsupported_rule_or_wrong_lens_is_rejected(self):
        with self.assertRaises(InputError):bd.snapshot(self.store,lens='work_visits',recurrence_order='infer-order')
        with self.assertRaises(InputError):bd.snapshot(self.store,lens='work',recurrence_order=work_order.VERSION)


if __name__=='__main__':unittest.main()
