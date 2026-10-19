import hashlib
import json
from pathlib import Path
import tempfile
import shutil
import subprocess
from types import SimpleNamespace
import unittest

from rilldex.reward_checks import check_artifacts, snapshot_artifact
from tracker import monitoring
from tracker.schema import InputError
from tracker.workspace_analysis import Workspace
import test_reward_detectors as helpers
from test_tracker import harbor


def recorded(text):
    data = text.encode()
    return dict(exists=True, size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest())


class ArtifactCallbackTests(unittest.TestCase):
    def check(self, records, rules=None):
        return check_artifacts(SimpleNamespace(inputs={'artifacts': records},
            config={'artifacts': {'test.py': {'nonempty': True}} if rules is None else rules}))

    def test_capture_real_bytes_missing_empty_unicode_and_read_errors(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'é.py'
            self.assertEqual(snapshot_artifact(path), {'exists': False})
            path.write_bytes(b'')
            self.assertEqual(snapshot_artifact(path), recorded(''))
            path.write_bytes('print("你好")\r\n'.encode())
            self.assertEqual(snapshot_artifact(path), recorded('print("你好")\r\n'))
            with self.assertRaises(OSError): snapshot_artifact(folder)

    def test_missing_capture_is_not_missing_file(self):
        for value in ({}, {'test.py': None}, {'test.py': {}},
                      {'test.py': {'exists': 0}}, {'test.py': {'exists': True}},
                      {'test.py': {'exists': True, 'size_bytes': False}},
                      {'test.py': {'exists': True, 'size_bytes': -1}}):
            self.assertEqual(self.check(value)['status'], 'unknown')
        for value, issue in [({'exists': False}, 'missing_file'), (recorded(''), 'empty_file')]:
            result = self.check({'test.py': value})
            self.assertEqual(result['status'], 'flagged')
            self.assertEqual(result['details']['violations'], [{'artifact': 'test.py', 'issue': issue}])

    def test_valid_edits_empty_optout_and_fixed_evaluator(self):
        baseline = recorded('assert solve(2) == 4')
        changed = recorded('print("ALL PASS")')
        self.assertEqual(self.check({'test.py': changed})['status'], 'clear')
        rules = {'test.py': {'sha256': baseline['sha256']}}
        self.assertEqual(self.check({'test.py': baseline}, rules)['status'], 'clear')
        result = self.check({'test.py': changed}, rules)
        self.assertEqual(result['details']['violations'][0]['issue'], 'digest_changed')
        self.assertEqual(self.check({'test.py': {'exists': True, 'size_bytes': 10}}, rules)['status'], 'unknown')
        self.assertEqual(self.check({'test.py': recorded('')}, {'test.py': {'nonempty': False}})['status'], 'clear')

    def test_known_violation_keeps_incomplete_capture_visible(self):
        result = self.check({'test.py': recorded('')}, {'test.py': {}, 'solution.py': {}})
        self.assertEqual(result['status'], 'flagged')
        self.assertEqual(result['details']['missing_capture'], ['solution.py'])

    def test_invalid_config_is_an_error(self):
        for rules in ([], {'': {}}, {'test.py': {'sha256': 'bad'}},
                      {'test.py': {'nonempty': 'true'}}, {'test.py': {'minimum_tests': 1}}):
            with self.assertRaises(InputError): self.check({}, rules)


class ArtifactPublicationTests(unittest.TestCase):
    setUp = helpers.RewardDetectorTests.setUp
    ingest = helpers.RewardDetectorTests.ingest
    rows = helpers.RewardDetectorTests.rows

    @unittest.skipUnless(shutil.which('node'), 'Node is needed for the generated worker')
    def test_ui_generated_worker_publishes_real_artifact_feedback(self):
        document = harbor(); document['evaluation_artifacts'] = {'answer.json': recorded('')}
        rid = self.ingest(document)
        code = subprocess.run([shutil.which('node'), '-e',
            "process.stdout.write(require('./tracker/web/custom-monitor-setup.js').script(JSON.parse(require('node:fs').readFileSync(0,'utf8'))));"],
            input=json.dumps(dict(template='artifacts', database=str(self.db), experiment='train',
                                  artifactNames='answer.json', rewardDefinition='delivery/v3')),
            text=True, encoding='utf-8', capture_output=True, check=True,
            cwd=Path(__file__).resolve().parents[1]).stdout
        namespace = {'__name__': 'generated_test'}
        exec(compile(code, 'artifact_worker.py', 'exec'), namespace)
        monitor = namespace['monitor']
        self.assertEqual(monitor.run(namespace['check_artifacts'])['published'], 1)
        self.assertEqual(self.rows(monitor)[rid]['value'], 1)

    def test_real_store_late_artifacts_restart_and_ui_values(self):
        document = harbor()
        self.ingest(document, name='artifact')
        monitor = Workspace(self.db, experiment='train', observer='source').reward_detector(
            'Required artifacts', version='1', description='Actual evaluator input integrity.',
            reward_definition='delivery/v3', stage='execution',
            inputs={'artifacts': '/raw/evaluation_artifacts'},
            config={'artifacts': {'solution.py': {}, 'test.py': {}}})
        self.assertEqual(monitor.run(check_artifacts)['published'], 1)
        self.assertEqual(next(iter(self.rows(monitor).values()))['unknown'], 1)
        document['evaluation_artifacts'] = {'solution.py': recorded(''), 'test.py': recorded('')}
        rid = self.ingest(document, revision=1, name='artifact')
        self.assertEqual(monitor.run(check_artifacts)['published'], 1)
        row = self.rows(monitor)[rid]
        self.assertEqual(row['value'], 1)
        self.assertEqual(len(row['details']['custom']['violations']), 2)
        self.assertEqual(row['details']['detector']['input_evidence']['artifacts']['value'], document['evaluation_artifacts'])
        self.assertEqual(monitor.run(lambda _: self.fail('Repeated unchanged work'))['skipped'], 1)
        document['evaluation_artifacts'] = {'solution.py': recorded('print(4)'), 'test.py': recorded('assert solve(2) == 4')}
        rid = self.ingest(document, revision=2, name='artifact')
        self.assertEqual(monitor.run(check_artifacts)['published'], 1)
        self.assertEqual(self.rows(monitor)[rid]['value'], 0)
        snapshot = next(m for m in monitoring.snapshot(self.store)['monitors'] if m['id'] == monitor.id)
        self.assertEqual(snapshot['detector_counts'], {'clear': 1})
        self.assertEqual(snapshot['series'][0]['bins'][0]['value'], 0)
