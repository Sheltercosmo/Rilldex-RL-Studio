"""Retained selector integrity and offline replay, not semantic accuracy."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from research import scoped_selector_trial as trial
from tracker.schema import InputError


class ScopedSelectorTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'selector'
        shutil.copytree(trial.DEST, self.root)
        self.addCleanup(patch.stopall)
        patch.object(trial, 'DEST', self.root).start()
        patch('urllib.request.urlopen', side_effect=AssertionError('Audit must be offline')).start()
        patch('urllib.request.build_opener', side_effect=AssertionError('Audit must be offline')).start()
        self.manifest = trial.read(self.root / 'manifest.json')

    def edit(self, path, transform):
        value = trial.read(path)
        transform(value)
        path.write_text(json.dumps(value), encoding='utf-8')

    def test_retained_wire_replays_exactly_without_a_provider(self):
        self.assertEqual(trial.audit(), trial.read(self.root / 'audit.json'))

    def test_changed_frozen_request_is_rejected(self):
        path = self.root / 'requests' / self.manifest['requests'][0]['file']
        self.edit(path, lambda value: value.update(model='different-model'))
        with self.assertRaisesRegex(InputError, 'Frozen request changed'):
            trial.audit()

    def test_wire_and_decision_must_match_including_usage(self):
        path = self.root / 'wire' / self.manifest['requests'][0]['file']
        self.edit(path, lambda value: value['response']['usage'].update(input_tokens=0))
        with self.assertRaisesRegex(InputError, 'Decision differs from retained wire'):
            trial.audit()

    def test_cached_selected_label_cannot_override_actual_argmax(self):
        path = self.root / 'decisions' / self.manifest['requests'][0]['file']
        self.edit(path, lambda value: value['answers']['choice'].update(value='plan'))
        with self.assertRaisesRegex(InputError, 'Cached raw argmax differs'):
            trial.audit()


if __name__ == '__main__':
    unittest.main()
