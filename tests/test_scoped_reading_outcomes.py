"""Handoff/integrity checks of retained proposals, not semantic gold labels."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from research.scoped_reading_outcomes import inspect,audit_reference_trial,export_candidates
from research.scoped_reading_trial import sha
from tracker.schema import InputError


SOURCE=Path(__file__).resolve().parents[1]/'research/scoped-reading-trial-2026-10-12'


class ScopedOutcomeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.source=self.root/'source'
        shutil.copytree(SOURCE,self.source,ignore=shutil.ignore_patterns('candidate-handoff'))

    def test_rejected_quote_retained_and_valid_candidates_use_real_queue(self):
        before={p.name:sha(p) for p in self.source.glob('*.json')}
        initial=inspect(self.source)
        self.assertEqual(initial['summary']['structurally_valid'],5)
        self.assertEqual(sum(r['status']=='rejected' for r in initial['rows']),1)
        with patch('urllib.request.urlopen',side_effect=AssertionError('No network in handoff')):
            result=export_candidates(self.source,self.root/'queue')
        self.assertEqual(result['summary'],dict(subjects=6,candidate_ready=6,selected=0))
        self.assertTrue(all(r['selected_activity'] is None for r in result['rows']))
        self.assertEqual(sum(r['origin_file']=='reference-output.json' for r in result['rows']),1)
        self.assertEqual(before,{p.name:sha(p) for p in self.source.glob('*.json')})
        self.assertEqual(len(list((self.root/'queue/candidates/responses').glob('*.json'))),6)
        self.assertFalse((self.root/'queue/decisions').exists())
        with self.assertRaisesRegex(InputError,'fresh'):export_candidates(self.source,self.root/'queue')

    def test_changed_original_output_cannot_be_hidden_by_a_successful_variant(self):
        path=self.source/'output-1.json';path.write_bytes(path.read_bytes()+b'\n')
        with self.assertRaisesRegex(InputError,'Original proposal outputs changed'):
            export_candidates(self.source,self.root/'queue')
        self.assertFalse((self.root/'queue').exists())

    def test_new_format_does_not_relax_source_identity_or_original_input_binding(self):
        path=self.source/'reference-output.json'
        response=json.loads(path.read_text(encoding='utf-8'))
        response['responses'][0]['request_hash']='wrong-source'
        path.write_text(json.dumps(response),encoding='utf-8')
        with self.assertRaisesRegex(InputError,'bind'):audit_reference_trial(self.source)
        path=self.source/'reference-packet.json';path.write_bytes(path.read_bytes()+b'\n')
        with self.assertRaisesRegex(InputError,'input changed'):audit_reference_trial(self.source)


if __name__=='__main__':unittest.main()
