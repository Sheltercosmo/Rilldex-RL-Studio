import copy
from pathlib import Path
import shutil
import subprocess
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

from tracker import semantic_catalog, semantic_collection, semantic_workspace as workspace
from tracker.schema import InputError, digest
from tracker.semantic_extraction import read, write
from tracker.store import Store
from tests.test_semantic_extraction import fixture, response
from tests.test_semantic_workspace import GENERATOR


class SemanticCollectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.collection = self.root/'collection'
        self.store = Store(self.root/'tracker.sqlite')
        self.script = self.root/'generator.py'; self.script.write_text(GENERATOR, encoding='utf-8')
        self.first = fixture(); self.second = copy.deepcopy(self.first)
        self.second['id'] = digest('second recorded rollout')[:24]
        self.second['metadata']['training_step'] = 2
        self.store.add([self.first, self.second])
        self.profiles = patch.object(semantic_catalog, 'PROFILES', {})
        self.profiles.start(); self.addCleanup(self.profiles.stop)

    def complete(self, run, *, context_policy=None, producer='test generator/1'):
        root = self.root/run['id']
        workspace.initialize(root, run, include_user=False, context_policy=context_policy)
        result = workspace.execute(root, response, command=[sys.executable, str(self.script)], producer=producer)
        self.assertEqual(result['status'], 'complete_local_extraction')
        for name in ('candidates', 'decisions', 'results'):
            shutil.copytree(root/name, self.collection/name, dirs_exist_ok=True)

    def test_one_observer_binds_every_rollout_and_reuses_id_regardless_of_order(self):
        for run in (self.first, self.second): self.complete(run)
        ids = [self.first['id'], self.second['id']]
        registered = semantic_collection.register(self.store, self.collection, ids, 'One protocol')
        repeat = semantic_collection.register(self.store, self.collection, ids[::-1], 'One protocol')
        self.assertEqual(registered, repeat)
        self.assertEqual(len(registered['members']), 2)
        self.assertEqual(set(registered['protocol']['stages']), {'partition', 'activity', 'content'})
        catalog = semantic_catalog.catalog(self.store)
        self.assertEqual({r['run_id'] for r in catalog['maps']}, set(ids))
        self.assertEqual({r['observer'] for r in catalog['maps']}, {registered['observer']})
        with self.store.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM semantic_observers').fetchone()[0], 1)
            self.assertEqual(c.execute('SELECT COUNT(DISTINCT run_id) FROM rollout_measurements WHERE observer=?',
                (registered['observer'],)).fetchone()[0], 2)
        for run in (self.first, self.second):
            loaded = semantic_catalog.load(run, registered['observer'], self.store)
            self.assertEqual(loaded['document']['source_hash'], digest(run))
        outside = copy.deepcopy(self.first); outside['id'] = 'unregistered'
        with self.assertRaisesRegex(InputError, 'outside'):
            semantic_catalog.load(outside, registered['observer'], self.store)

    def test_changed_member_is_unavailable_without_hiding_unchanged_members(self):
        for run in (self.first, self.second): self.complete(run)
        registered = semantic_collection.register(self.store, self.collection,
            [self.first['id'], self.second['id']], 'Frozen')
        raw = read(self.collection/'results'/f'{self.first["id"]}.json')
        note = {'schema':'semantic-source-review/1', 'source_hash':digest(self.first),
            'extraction_hash':digest(raw), 'annotator':'test reviewer',
            'notes':[{'text':'New review after collection registration.', 'evidence':[raw['units'][0]['source']],
                'unit_ids':[raw['units'][0]['id']]}]}
        write(self.collection/'reviews'/self.first['id']/f'{digest(raw)}.json', note)
        listing = semantic_catalog.catalog(self.store)
        self.assertEqual([r['run_id'] for r in listing['maps']], [self.second['id']])
        self.assertEqual(listing['unavailable'][0]['observer'], registered['observer'])
        changed = copy.deepcopy(self.second); changed['events'][1]['text'] += ' New source.'
        with self.assertRaisesRegex(InputError, 'another source'):
            semantic_catalog.load(changed, registered['observer'], self.store)

    def test_incomplete_or_incompatible_collection_is_not_published(self):
        self.complete(self.first)
        ids = [self.first['id'], self.second['id']]
        with self.assertRaisesRegex(InputError, 'complete extraction'):
            semantic_collection.register(self.store, self.collection, ids, 'Incomplete')
        self.complete(self.second, producer='different proposer/2')
        with self.assertRaisesRegex(InputError, 'different extraction protocols'):
            semantic_collection.register(self.store, self.collection, ids, 'Mixed')
        self.assertEqual(semantic_catalog.registered(self.store), {})

    def test_context_changes_cannot_silently_share_a_protocol(self):
        self.complete(self.first)
        self.complete(self.second, context_policy={'schema':'readable-context/2', 'recent_events':1,
            'max_event_chars':2000, 'extra_ranges':[]})
        with self.assertRaisesRegex(InputError, 'different decision protocols'):
            semantic_collection.register(self.store, self.collection,
                [self.first['id'], self.second['id']], 'Different context')
        self.assertEqual(semantic_catalog.registered(self.store), {})

    def test_collection_cli_registers_without_a_single_run_workspace_configuration(self):
        self.complete(self.first)
        completed = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'rilldex', '--db', str(self.store.path),
            'semantic', 'register-collection', str(self.collection), '--run-ids', self.first['id'],
            '--label', 'CLI collection'], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(completed.returncode, 0, completed.stderr)
        registered = json.loads(completed.stdout)
        self.assertEqual(registered['members'], [self.first['id']])
        self.assertIn(registered['observer'], semantic_catalog.registered(self.store))


if __name__ == '__main__': unittest.main()
