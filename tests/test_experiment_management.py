import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from rilldex import Workspace
from tracker.experiment_catalog import catalog
from tracker.experiment_management import organize_many, selection
from tracker.run_records import organize, receive
from tracker.schema import InputError
from tracker.store import Store
from tracker.trainer_telemetry import TrainerTelemetry
import test_generation_cohort_transport as transport


def capture(store, experiment, project='original'):
    receive(store, dict(schema='run-records/1', producer='worker', experiment=experiment, records=[dict(
        id='manifest', session='one', kind='manifest', observed_at='2026-10-22T00:00:00Z',
        payload=dict(name=experiment, project=project, config={'seed':42}, runtime={}))]))


class ExperimentManagementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.db = self.root/'study.sqlite'; self.store = Store(self.db)
        self.registry = patch.dict(os.environ, RILLDEX_WORKSPACE_REGISTRY=str(self.root/'registry.sqlite'))
        self.registry.start(); self.addCleanup(self.registry.stop)
        for name in ('a', 'b', 'c'): capture(self.store, name)

    def snapshot(self, table):
        with self.store.connect() as c:
            return [tuple(r) for r in c.execute('SELECT * FROM '+table+' ORDER BY 1')]

    def test_bulk_updates_preserve_capture_and_unselected_labels(self):
        organize(self.store, experiment='a', title='Friendly', tags=['keep', 'old'], notes='review notes')
        organize(self.store, experiment='b', tags=['different'])
        before = self.snapshot('run_records')
        result = Workspace(self.db).organize_experiments(['a', 'b'], project='Review λ',
            add_tags=['new', 'new'], remove_tags=['old'], pinned=True, archived=True)
        self.assertEqual(result['updated'], 2)
        self.assertEqual(catalog(self.store)['total'], 1)
        rows = {r['experiment']:r for r in catalog(self.store, state='archived', project='Review λ')['rows']}
        self.assertEqual(rows['a']['tags'], ['keep', 'new'])
        self.assertEqual(rows['b']['tags'], ['different', 'new'])
        self.assertEqual((rows['a']['title'], rows['a']['notes']), ('Friendly', 'review notes'))
        self.assertEqual(catalog(self.store)['rows'][0]['project'], 'original')
        self.assertEqual(self.snapshot('run_records'), before)
        organize_many(self.store, experiments=['a', 'b'], project='', pinned=False, archived=False)
        self.assertEqual(catalog(self.store, project='')['total'], 2)
        self.assertEqual(catalog(self.store, state='pinned')['total'], 0)
        self.assertEqual(selection(Store(self.db), experiments=['a'])['rows'][0]['title'], 'Friendly')

    def test_unknown_or_overfull_run_rolls_back_every_change(self):
        before = self.snapshot('experiment_labels')
        with self.assertRaises(InputError):
            organize_many(self.store, experiments=['a', 'missing'], project='wrong')
        self.assertEqual(self.snapshot('experiment_labels'), before)
        organize(self.store, experiment='b', tags=['tag-'+str(i) for i in range(20)])
        before = self.snapshot('experiment_labels')
        with self.assertRaises(InputError):
            organize_many(self.store, experiments=['a', 'b'], project='wrong', add_tags=['extra'])
        self.assertEqual(self.snapshot('experiment_labels'), before)

    def test_selection_ignores_list_filters_but_checks_environment_and_latest_logs(self):
        organize_many(self.store, experiments=['a'], archived=True)
        self.assertEqual([r['experiment'] for r in selection(self.store, experiments=['c','a'])['rows']], ['c','a'])
        self.assertEqual(selection(self.store, experiments=['a'])['rows'][0]['logs'], 0)
        TrainerTelemetry(self.store, experiment='a', framework='trl-grpo', framework_version='fixture',
            objective='grpo', producer='worker', session='one', environment='software').log({'reward':1}, step=1)
        result = selection(self.store, experiments=['a', 'b', 'missing'], environment='software')
        self.assertEqual(result['rows'][0]['logs'], 1)
        self.assertEqual(result['unavailable'], ['b', 'missing'])
        self.assertEqual(selection(self.store, experiments=['a'], environment='robotics')['rows'], [])

    def test_validation_never_changes_labels(self):
        before = self.snapshot('experiment_labels')
        cases = [dict(experiments=[]), dict(experiments=['a','a']), dict(experiments=[{}]),
                 dict(experiments=['a'], pinned=1), dict(experiments=['a'], project=4),
                 dict(experiments=['a'], add_tags='tag'), dict(experiments=['a'], add_tags=[' ']),
                 dict(experiments=['a'], add_tags=['same'], remove_tags=['same']),
                 dict(experiments=['a']), dict(experiments=['a'], add_tags=[]),
                 dict(experiments=['run-'+str(i) for i in range(501)], archived=True)]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(InputError): organize_many(self.store, **case)
        self.assertEqual(self.snapshot('experiment_labels'), before)
        with self.assertRaises(InputError): selection(self.store, experiments=['a'], environment={})

    def test_concurrent_additions_preserve_both_tags(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda tag: organize_many(self.store, experiments=['a','b'], add_tags=[tag]), ['one','two']))
        for row in selection(self.store, experiments=['a','b'])['rows']:
            self.assertEqual(set(row['tags']), {'one','two'})

    def test_large_selection_and_same_ids_in_another_workspace(self):
        for i in range(500): capture(self.store, 'run-'+str(i))
        ids = ['run-'+str(i) for i in range(500)]
        other = Store(self.root/'other.sqlite'); capture(other, ids[0])
        organize_many(self.store, experiments=ids, project='Large sweep', archived=True)
        self.assertEqual(len(selection(self.store, experiments=ids)['rows']), 500)
        self.assertEqual(catalog(self.store, state='archived')['total'], 500)
        self.assertEqual(catalog(other)['rows'][0]['project'], 'original')

    def test_scoped_python_api_cannot_change_another_run(self):
        with self.assertRaises(InputError): Workspace(self.db, experiment='a').organize_experiments(['b'], pinned=True)
        Workspace(self.db, experiment='a').organize_experiments(['a'], pinned=True)
        Workspace(self.db, experiment='a').organize(project='')
        self.assertEqual(catalog(self.store, project='')['total'], 1)

    start_server = transport.GenerationCohortTransportTests.start_server
    stop_server = staticmethod(transport.GenerationCohortTransportTests.stop_server)

    def test_http_bulk_allowlist_and_readback(self):
        base = self.start_server()
        def post(route, value):
            with urlopen(Request(base+route, data=json.dumps(value).encode(), headers={'Content-Type':'application/json'}), timeout=10) as response:
                return json.load(response)
        for value in [dict(experiments=['a'], notes='unexpected'), dict(experiments=['a'], archived=1)]:
            with self.assertRaises(HTTPError) as error: post('/api/experiments/organize', value)
            self.assertEqual(error.exception.code, 400)
        self.assertEqual(post('/api/experiments/organize', dict(experiments=['a','b'], archived=True))['updated'], 2)
        self.assertTrue(all(r['archived'] for r in post('/api/experiments/selection', dict(experiments=['a','b']))['rows']))


if __name__ == '__main__': unittest.main()
