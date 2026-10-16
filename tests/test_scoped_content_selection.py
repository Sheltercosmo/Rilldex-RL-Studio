"""Actual retained content decisions and source evidence survive offline replay."""
from pathlib import Path
import json
import shutil
import tempfile
import unittest
from unittest.mock import patch

from research import scoped_content_selection as trial
from tracker.schema import InputError


class ScopedContentSelectionTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)/'selection'
        source=trial.ROOT/'research/scoped-content-selection-envelope-2026-10-12'
        shutil.copytree(source,self.root)
        self.addCleanup(patch.stopall);patch.object(trial,'DEST',self.root).start()
        patch('urllib.request.urlopen',side_effect=AssertionError('No provider in audit')).start()
        patch('urllib.request.build_opener',side_effect=AssertionError('No provider in audit')).start()

    def test_selected_fields_replay_from_the_exact_wire_candidates(self):
        audit=trial.audit()
        self.assertEqual(audit,trial.read(self.root/'audit.json'))
        for row in audit['rows']:
            self.assertEqual(row['status'],'selected')
            self.assertTrue(row['fields']['work_target']['text'].strip())

    def test_recorded_usage_cannot_differ_between_decision_and_wire(self):
        path=next((self.root/'wire').glob('*.json'))
        value=trial.read(path);value['response']['usage']['input_tokens']=0
        path.write_text(json.dumps(value),encoding='utf-8')
        with self.assertRaisesRegex(InputError,'differs from retained wire'):trial.audit()


if __name__=='__main__':unittest.main()
