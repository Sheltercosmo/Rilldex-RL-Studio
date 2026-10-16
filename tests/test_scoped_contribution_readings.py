"""Protocol integrity tests; generated fixture labels are not semantic gold."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from tracker import semantic_workspace as workspace, semantic_collection
from tracker.contribution_readings import (
    VERSION, SCOPED_VERSION, generation_request, validate, routing_for,
)
from tracker.schema import InputError, digest
from tracker.semantic_extraction import (
    ACTIVITIES, ACTIVITY_ROUTING, WORK_PHASE_ACTIVITY_ROUTING,
    WORK_ORGANIZATION_ACTIVITY_ROUTING, FileCandidates, activity_choices,
    audit_result, read, write, windows,
)
from tracker.store import Store
from tracker.adapters import normalize
from tests.test_contribution_readings import reading
from tests.test_semantic_extraction import fixture, response
from tests.test_semantic_workspace import GENERATOR

ROUTES = (ACTIVITY_ROUTING, WORK_PHASE_ACTIVITY_ROUTING, WORK_ORGANIZATION_ACTIVITY_ROUTING)


class ScopedReadingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.run = fixture()
        self.script = self.root/'generator.py'; self.script.write_text(GENERATOR, encoding='utf-8')

    def complete(self, root, run=None, *, routing=WORK_PHASE_ACTIVITY_ROUTING, version=SCOPED_VERSION):
        run = run or self.run
        workspace.initialize(root, run, include_user=False, activity_routing=routing, reading_protocol=version)
        result = workspace.execute(root, response, command=[sys.executable, str(self.script)], producer='fixture/1')
        self.assertEqual(result['status'], 'complete_local_extraction')
        return read(root/'results'/f'{run["id"]}.json')

    def test_every_route_binds_generation_selection_and_replay_with_raw_argmax(self):
        for routing in ROUTES:
            with self.subTest(routing=routing):
                root = self.root/routing.split('/')[0]
                result = self.complete(root, routing=routing)
                unit = result['units'][0]
                generated = read(root/'candidates/requests'/f'{unit["activity_reading_request"]}.json')
                selected = read(root/'decisions'/f'{unit["activity_request"]}.json')
                criteria = selected['request']['questions']['choice']['criteria']
                expected = deepcopy(generated['activity_definitions'])
                proposals = selected['request']['state']['activity_reading_candidates']['readings']
                for row in proposals:
                    expected[row['activity']] += ' Candidate interpretation for this source: '+row['text']
                self.assertEqual(criteria, expected)
                self.assertEqual(generated['activity_definitions'], activity_choices(routing))
                self.assertEqual(generated['activity_routing'], routing)
                self.assertEqual(unit['activity'], 'orient')
                # Fixture returns another choice and zero confidence: neither controls selection.
                self.assertNotEqual(selected['response']['answers']['choice']['choice'], unit['activity'])
                self.assertTrue(audit_result(self.run, result, root)['argmax_replayed'])
                repeated = workspace.execute(root, lambda _: self.fail('Must replay exact saved decisions'),
                    command=[sys.executable, str(self.script)], producer='fixture/1')
                self.assertEqual(repeated['last_execution']['candidate_calls_this_execution'], 0)
                self.assertEqual(repeated['last_execution']['provider_responses_this_execution'], 0)

    def test_legacy_request_and_cache_remain_legacy_and_cannot_satisfy_v2(self):
        ref = windows(self.run)[0]
        legacy = FileCandidates(self.root/'c', contribution_readings=True, activity_routing=WORK_PHASE_ACTIVITY_ROUTING)
        old = legacy.readings(self.run, ref); req = read(self.root/'c/requests'/f'{old["request_hash"]}.json')
        self.assertEqual(req, generation_request(self.run, ref))
        self.assertEqual(req['activity_definitions'], ACTIVITIES)
        self.assertNotIn('reading_protocol', req)
        self.assertNotIn('activity_routing', req)
        write(self.root/'c/responses'/f'{old["request_hash"]}.json', reading(req))
        modern = FileCandidates(self.root/'c', contribution_readings=True,
            activity_routing=WORK_PHASE_ACTIVITY_ROUTING, reading_protocol=SCOPED_VERSION)
        new = modern.readings(self.run, ref)
        self.assertEqual(new['status'], 'needs_activity_readings')
        self.assertNotEqual(new['request_hash'], old['request_hash'])
        write(self.root/'c/responses'/f'{new["request_hash"]}.json', reading(req))
        with self.assertRaisesRegex(InputError, 'bind to this source request'):
            modern.readings(self.run, ref)
        self.assertEqual(legacy.readings(self.run, ref)['status'], 'ready')
        self.assertEqual(routing_for(VERSION, WORK_ORGANIZATION_ACTIVITY_ROUTING), WORK_ORGANIZATION_ACTIVITY_ROUTING)

    def test_v2_source_form_and_definitions_cannot_be_forged_with_fresh_hashes(self):
        ref = windows(self.run)[0]
        req = generation_request(self.run, ref, workspace.DEFAULT_CONTEXT,
            activity_routing=WORK_PHASE_ACTIVITY_ROUTING, version=SCOPED_VERSION)
        self.assertEqual(req['source_form']['actor'], 'agent')
        self.assertEqual(req['source_form']['kind'], self.run['events'][1]['kind'])
        self.assertNotIn('FUTURE', json.dumps(req))
        self.assertEqual(validate(self.run, req, reading(req))['reading_protocol'], SCOPED_VERSION)
        for field in ('source_form', 'activity_definitions', 'contribution_scope', 'prefix'):
            changed = deepcopy(req)
            changed[field] = [] if field == 'prefix' else 'unsupported replacement'
            with self.subTest(field=field), self.assertRaisesRegex(InputError, 'differs from its source'):
                validate(self.run, changed, reading(changed))
        bad = reading(req); bad['reading_protocol'] = VERSION
        with self.assertRaisesRegex(InputError, 'cannot change the reading protocol'):
            validate(self.run, req, bad)
        future = reading(req)
        future['readings'][0]['evidence'].append({'event_id':self.run['events'][-1]['id'], 'quote':'FUTURE'})
        with self.assertRaises(InputError): validate(self.run, req, future)

    def test_rehashed_scope_or_criteria_changes_fail_publication_audit(self):
        from tracker.semantic_extraction import replay_decision
        root = self.root/'v2'; result = self.complete(root)
        unit = result['units'][0]
        original = read(root/'decisions'/f'{unit["activity_request"]}.json')
        for field, pattern in (('scope', 'contribution scope'), ('criteria', 'criteria differ'), ('routing', 'declared routing')):
            altered = deepcopy(result); saved = deepcopy(original)
            if field == 'scope': saved['request']['state']['contribution_scope'] = 'Changed rule'
            elif field == 'criteria': saved['request']['questions']['choice']['criteria']['orient'] += ' Changed rule'
            else: saved['request']['state']['activity_routing'] = ACTIVITY_ROUTING
            saved['answers'] = replay_decision(saved)
            key = digest(saved['request']); write(root/'decisions'/f'{key}.json', saved)
            altered['units'][0]['activity_request'] = key
            with self.subTest(field=field), self.assertRaisesRegex(InputError, pattern):
                audit_result(self.run, altered, root)
        altered = deepcopy(result); altered['activity_reading_contract'] = VERSION
        with self.assertRaisesRegex(InputError, 'reading request differs'):
            audit_result(self.run, altered, root)

    def test_source_form_retains_speaker_and_dispatch_without_inferring_effects(self):
        run = normalize({'schema_version':'ATIF-v1.7', 'session_id':'scope-control',
            'agent':{'name':'test','version':'1'}, 'steps':[
                {'step_id':1, 'source':'user', 'message':'Check fares first.'},
                {'step_id':2, 'source':'agent', 'message':'I will check fares.',
                 'tool_calls':[{'tool_call_id':'x','function_name':'find_fares','arguments':{'refundable':True}}]}]})[0]
        refs = windows(run, include_user=True)
        forms = [generation_request(run, ref, version=SCOPED_VERSION)['source_form'] for ref in refs]
        self.assertEqual([form['actor'] for form in forms], ['user', 'agent', 'agent'])
        self.assertEqual(forms[-1]['kind'], 'action')
        self.assertNotEqual(forms[-2]['kind'], 'action')
        self.assertTrue(all(set(form) == {'kind','actor','meaning'} for form in forms))

    def test_pending_readings_are_audited_before_classification(self):
        from tracker.semantic_extraction import Pipeline
        root = self.root/'pending'
        provider = FileCandidates(root/'c', contribution_readings=True,
            activity_routing=WORK_PHASE_ACTIVITY_ROUTING, reading_protocol=SCOPED_VERSION)
        result = Pipeline(root, provider, response).run(self.run)
        self.assertEqual(result['units'][0]['status'], 'needs_activity_readings')
        self.assertTrue(audit_result(self.run, result, root)['argmax_replayed'])
        bad = deepcopy(result); bad['activity_reading_contract'] = VERSION
        with self.assertRaisesRegex(InputError, 'Pending activity readings'):
            audit_result(self.run, bad, root)

    def test_workspace_protocol_is_frozen_and_cli_exposes_the_selected_protocol(self):
        root = self.root/'legacy'; workspace.initialize(root, self.run)
        self.assertNotIn('reading_protocol', workspace.load(root)[0])
        with self.assertRaisesRegex(InputError, 'configuration changed'):
            workspace.initialize(root, self.run, reading_protocol=SCOPED_VERSION)
        with self.assertRaisesRegex(InputError, 'Unknown contribution reading protocol'):
            workspace.initialize(self.root/'invalid', self.run, reading_protocol='unknown')
        self.assertFalse((self.root/'invalid').exists())
        store = Store(self.root/'cli.sqlite'); store.add([self.run])
        dest = self.root/'cli'
        result = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'rilldex', '--db', str(store.path),
            'semantic', 'prepare', str(dest), '--run-id', self.run['id'], '--agent-only',
            '--activity-routing', WORK_PHASE_ACTIVITY_ROUTING, '--reading-protocol', SCOPED_VERSION],
            capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['reading_protocol'], SCOPED_VERSION)
        self.assertEqual(workspace.load(dest)[0]['reading_protocol'], SCOPED_VERSION)
        changed = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'rilldex', '--db', str(store.path),
            'semantic', 'prepare', str(dest), '--reading-protocol', VERSION],
            capture_output=True, text=True, encoding='utf-8')
        self.assertNotEqual(changed.returncode, 0)
        self.assertIn('Provide --run-id', changed.stderr)
        self.assertEqual(workspace.load(dest)[0]['reading_protocol'], SCOPED_VERSION)
        pending = workspace.execute(dest, lambda _: self.fail('No candidates are supplied'))
        self.assertEqual(pending['status'], 'needs_work')
        self.assertEqual(workspace.audit(dest)['validation']['checkpoint']['argmax_replayed'], True)

    def test_collection_cannot_pool_protocol_versions(self):
        other = deepcopy(self.run); other['id'] = digest('separate recorded rollout')[:24]
        store = Store(self.root/'collection.sqlite'); store.add([self.run, other])
        collection = self.root/'collection'
        for run, version in ((self.run, VERSION), (other, SCOPED_VERSION)):
            root = self.root/run['id']; self.complete(root, run, version=version)
            for name in ('candidates', 'decisions', 'results'):
                shutil.copytree(root/name, collection/name, dirs_exist_ok=True)
        with self.assertRaisesRegex(InputError, 'different extraction protocols'):
            semantic_collection.register(store, collection, [self.run['id'], other['id']], 'Must reject mixing')
        with store.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM semantic_observers').fetchone()[0], 0)


if __name__ == '__main__': unittest.main()
