"""Envelope recovery preserves rejected evidence and original model output."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from research import scoped_content_envelope as trial
from tracker.schema import InputError


class ScopedEnvelopeTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)/'content'
        shutil.copytree(trial.original.DEST,self.root)
        self.addCleanup(patch.stopall)
        patch.object(trial.original,'DEST',self.root).start()
        patch.object(trial,'DEST',self.root/'response-envelope').start()
        patch('urllib.request.urlopen',side_effect=AssertionError('No provider in audit')).start()
        patch('urllib.request.build_opener',side_effect=AssertionError('No provider in audit')).start()

    def test_retained_handoff_replays_without_changing_the_strict_result(self):
        self.assertEqual(trial.audit(),trial.read(trial.DEST/'audit.json'))
        self.assertEqual(trial.original.audit(),trial.read(self.root/'candidate-audit.json'))
        rejected=[r for r in trial.audit()['rows'] if r['status']=='rejected']
        self.assertEqual(len(rejected),1)
        self.assertEqual(rejected[0]['reason'],'Evidence mismatch')
        self.assertFalse((trial.DEST/'candidates/responses'/f"{rejected[0]['request_hash']}.json").exists())

    def test_changed_original_payload_is_detected(self):
        path=self.root/'output-3.json';path.write_bytes(path.read_bytes()+b'\n')
        with self.assertRaisesRegex(InputError,'Original content payload changed'):trial.audit()

    def test_rewriting_a_valid_candidate_is_not_metadata_binding(self):
        row=next(r for r in trial.audit()['rows'] if r['status']=='ready')
        path=trial.DEST/'candidates/responses'/f"{row['request_hash']}.json"
        value=trial.read(path);value['candidates'][0]['fields']['summary']['text']='Invented success.'
        path.write_text(json.dumps(value),encoding='utf-8')
        with self.assertRaisesRegex(InputError,'exact original payload'):trial.audit()


if __name__=='__main__':unittest.main()
