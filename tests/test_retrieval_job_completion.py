"""A partially produced file must not count as a completed candidate job."""
import shutil
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from research import retrieval_rollout_trial as trial
from research.retrieval_final_output import KEY
from tracker.schema import InputError


class RetrievalJobCompletionTests(unittest.TestCase):
    def setUp(self):
        original=trial.DEST/'jobs'/KEY
        config,run=trial.workspace.load(trial.OBSERVER)
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name);self.job=self.root/'jobs'/KEY;self.job.mkdir(parents=True)
        for name in ('packet.json','dispatch.json','output.json'):
            shutil.copyfile(original/name,self.job/name)
        self.addCleanup(patch.stopall)
        patch.object(trial,'DEST',self.root).start()
        patch.object(trial,'OBSERVER',self.root/'observer').start()
        patch.object(trial.workspace,'load',return_value=(config,run)).start()

    def test_arrival_is_not_completion_and_sealed_payload_imports(self):
        trial.ingest_outputs()
        self.assertFalse((self.job/'import.json').exists())
        trial.seal_job(KEY);trial.ingest_outputs()
        self.assertEqual(trial.read(self.job/'import.json')['status'],'accepted')
        self.assertTrue((self.root/'observer/candidates/responses'/f'{KEY}.json').exists())

    def test_later_write_cannot_silently_replace_completed_payload(self):
        trial.seal_job(KEY)
        with (self.job/'output.json').open('a',encoding='utf8') as f:f.write('\n')
        with self.assertRaisesRegex(InputError,'Sealed output changed'):trial.ingest_outputs()
        self.assertFalse((self.job/'import.json').exists())

    def test_snapshot_change_is_detected(self):
        trial.seal_job(KEY)
        (self.job/'sealed-output.json').write_text('{}',encoding='utf8')
        with self.assertRaisesRegex(InputError,'Sealed output changed'):trial.ingest_outputs()
