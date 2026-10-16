"""Source and stage boundaries for retained category-conditioned proposals."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from research import scoped_content_trial as trial
from tracker.schema import InputError


class ScopedContentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'content'
        shutil.copytree(trial.DEST, self.root)
        self.addCleanup(patch.stopall)
        patch.object(trial, 'DEST', self.root).start()
        patch('urllib.request.urlopen', side_effect=AssertionError('No provider in audit')).start()
        patch('urllib.request.build_opener', side_effect=AssertionError('No provider in audit')).start()

    def test_proposals_replay_and_cannot_masquerade_as_selected_content(self):
        audit = trial.audit()
        self.assertEqual(audit, trial.read(self.root / 'candidate-audit.json'))
        self.assertEqual(audit['usage']['jev_calls'], 0)
        self.assertTrue(all(row['status'] in {'ready', 'rejected'} for row in audit['rows']))
        self.assertFalse((self.root / 'decisions').exists())

    def test_fresh_contexts_separate_different_cutoffs_of_the_same_trace(self):
        bindings = trial.read(self.root / 'bindings.json')
        for packet in trial.read(self.root / 'manifest.json')['packets']:
            run_ids = [bindings[key]['run']['id'] for key in packet['request_hashes']]
            self.assertEqual(len(run_ids), len(set(run_ids)))

    def test_changed_source_packet_stops_before_accepting_outputs(self):
        path = self.root / 'packet-1.json'
        path.write_bytes(path.read_bytes() + b'\n')
        with self.assertRaisesRegex(InputError, 'Content packet changed'):
            trial.audit()

    def test_unsupported_source_quote_is_rejected_without_repairing_it(self):
        path = self.root / 'output-1.json'
        output = trial.read(path)
        response = output['responses'][0]
        key = response['request_hash']
        response['candidates'][0]['fields']['summary']['evidence'] = [
            {'event_id': 'r', 'quote': 'This sentence was never in the supplied trace.'}]
        path.write_text(json.dumps(output), encoding='utf-8')
        before = path.read_bytes()
        audit = trial.audit()
        row = next(row for row in audit['rows'] if row['request_hash'] == key)
        self.assertEqual(row['status'], 'rejected')
        self.assertEqual(path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
