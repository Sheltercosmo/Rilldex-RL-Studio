import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tracker import semantic_workspace as workspace
from tracker.schema import InputError, digest, dumps
from tracker.semantic_budget import BudgetReached, ExecutionBudget, summary
from tracker.semantic_extraction import read, write
from tests.test_semantic_extraction import fixture, response
from tests.test_semantic_workspace import GENERATOR


class SemanticBudgetTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name); self.work = self.root / 'work'; self.run = fixture()
        self.script = self.root / 'generator.py'; self.script.write_text(GENERATOR, encoding='utf-8')
        workspace.initialize(self.work, self.run, include_user=False)

    def execute(self, transport=response, **limits):
        return workspace.execute(self.work, transport, command=[sys.executable, str(self.script)],
                                 producer='authored fixture/1', budget_limits=limits)

    def test_resumes_each_selected_stage_without_rebilling_cached_work(self):
        first = self.execute(jev_requests=1)
        self.assertEqual(first['status'], 'budget_reached')
        self.assertEqual(first['last_execution']['budget_used']['jev_requests'], 1)
        self.assertEqual(first['coverage']['selected_units'], 0)
        self.assertEqual(first['coverage']['visited_windows'], 1)
        self.assertEqual(first['unit_status_counts'], {'needs_activity': 1})
        self.assertFalse(first['last_complete_result_present'])
        self.assertIn('interrupted', workspace.audit(self.work)['validation']['checkpoint']['status'])
        second = self.execute(jev_requests=1)
        self.assertEqual(second['status'], 'budget_reached')
        self.assertEqual(second['coverage']['selected_source_fraction'], 0)
        self.assertEqual(second['unit_status_counts'], {'needs_content_selection': 1})
        third = self.execute(jev_requests=1)
        self.assertEqual(third['status'], 'complete_local_extraction')
        self.assertEqual(third['coverage']['selected_source_fraction'], 1)
        self.assertEqual(third['provider_usage']['providers']['jev']['attempts'], 3)
        self.assertEqual(third['provider_usage']['providers']['candidate']['attempts'], 3)
        result = read(self.work / 'results' / f'{self.run["id"]}.json')
        replay = self.execute(lambda _: self.fail('Cached pass must not call provider'),
                              jev_requests=0, candidate_requests=0, input_bytes=0)
        self.assertEqual(replay['last_execution']['budget_used'],
                         {'jev_requests': 0, 'candidate_requests': 0, 'input_bytes': 0})
        self.assertEqual(read(self.work / 'results' / f'{self.run["id"]}.json'), result)
        self.assertEqual(workspace.audit(self.work)['saved_decisions'], 3)

    def test_zero_candidate_limit_stops_before_process_and_preserves_queue(self):
        self.script.write_text("raise RuntimeError('must not start')", encoding='utf-8')
        result = self.execute(candidate_requests=0)
        self.assertEqual(result['last_execution']['budget_stop']['limit'], 'candidate_requests')
        self.assertEqual(result['provider_usage']['providers'], {})
        self.assertEqual(len(result['requests_without_responses']), 1)
        self.assertEqual(result['coverage']['unvisited_windows'], 1)

    def test_payload_budget_counts_utf8_and_both_providers_before_side_effect(self):
        request = {'source': {'text': '检查 café'}}
        jev_size = len(dumps(request).encode('utf-8'))
        candidate_size = len(dumps({'request_hash': digest(request), 'request': request}).encode('utf-8'))
        self.assertGreater(jev_size, len(dumps(request)))
        budget = ExecutionBudget(self.work, 7, {'input_bytes': jev_size + candidate_size - 1})
        budget.invoke('jev', request, lambda: {})
        with self.assertRaises(BudgetReached) as caught:
            budget.invoke('candidate', request, lambda: self.fail('Over-budget request started'))
        self.assertEqual(caught.exception.reason['limit'], 'input_bytes')
        self.assertEqual(budget.used['candidate_requests'], 0)
        exact = ExecutionBudget(self.work, 8, {'input_bytes': candidate_size})
        exact.invoke('candidate', request, lambda: {})
        self.assertEqual(exact.used['input_bytes'], candidate_size)

    def test_timeout_or_invalid_response_is_counted_and_sensitive_errors_are_not_stored(self):
        def failed(_): raise TimeoutError('private provider message')
        with self.assertRaises(TimeoutError): self.execute(failed)
        status = workspace.status(self.work)
        self.assertEqual(status['last_execution']['budget_used']['jev_requests'], 1)
        self.assertEqual(status['provider_usage']['providers']['jev']['statuses'], {'failed_or_interrupted': 1})
        self.assertEqual(status['provider_usage']['providers']['jev']['attempts_without_reported_usage'], 1)
        for path in self.work.rglob('*.json'):
            self.assertNotIn('private provider message', path.read_text(encoding='utf-8'))
        self.assertEqual(self.execute()['provider_usage']['providers']['jev']['attempts'], 4)

    def test_failed_candidate_process_consumes_attempt_before_return(self):
        self.script.write_text('import sys; sys.exit(3)', encoding='utf-8')
        with self.assertRaisesRegex(InputError, 'exit code 3'): self.execute()
        status = workspace.status(self.work)
        self.assertEqual(status['last_execution']['candidate_calls_this_execution'], 1)
        self.assertEqual(status['last_execution']['budget_used']['candidate_requests'], 1)
        self.assertEqual(status['provider_usage']['providers']['candidate']['statuses'], {'failed_or_interrupted': 1})
        self.assertFalse(status['last_complete_result_present'])

    def test_attempt_is_journaled_before_call_and_unfinished_attempt_is_unknown(self):
        budget = ExecutionBudget(self.work, 9)
        def inspect():
            row = read(next((self.work / 'attempts').glob('*.json')))
            self.assertEqual(row['status'], 'started')
            self.assertEqual(row['execution_id'], 9)
            return {'usage': {'input_tokens': 12, 'output_tokens': 2,
                              'total_tokens': True, 'private': 'not persisted'}}
        budget.invoke('jev', {'state': {'stage': 'activity'}}, inspect)
        write(self.work / 'attempts' / 'crashed.json', {
            'provider': 'jev', 'stage': 'content', 'status': 'started', 'input_bytes': 20})
        usage = summary(self.work)['providers']['jev']
        self.assertEqual(usage['reported_usage'], {'input_tokens': 12, 'output_tokens': 2})
        self.assertEqual(usage['usage_observations'], {'input_tokens': 1, 'output_tokens': 1})
        self.assertEqual(usage['attempts_without_reported_usage'], 1)
        self.assertEqual(usage['statuses'], {'returned': 1, 'started': 1})

    def test_stopped_new_pass_cannot_present_previous_checkpoint_as_current_coverage(self):
        self.execute()
        published = read(self.work / 'results' / f'{self.run["id"]}.json')
        # Simulate a missing cached decision, without altering the published snapshot.
        first = next((self.work / 'decisions').glob('*.json'))
        first.unlink()
        stopped = self.execute(jev_requests=0)
        self.assertEqual(stopped['status'], 'budget_reached')
        self.assertEqual(stopped['coverage']['selected_units'], 0)
        self.assertTrue(stopped['last_complete_result_present'])
        self.assertEqual(read(self.work / 'results' / f'{self.run["id"]}.json'), published)

    def test_bad_limits_fail_before_any_candidate_or_request_attempt(self):
        for limits in ({'jev_requests': -1}, {'candidate_requests': True}, {'input_bytes': 0.5}, {'token_limit': 1}):
            with self.subTest(limits=limits), self.assertRaises(InputError): self.execute(**limits)
        self.assertFalse((self.work / 'attempts').exists())

    def test_cli_zero_allowance_needs_no_key_or_generator(self):
        command = [sys.executable, '-X', 'utf8', '-m', 'rilldex', '--db', str(self.root / 'cli.sqlite'),
                   'semantic', 'run', str(self.work), '--max-new-calls', '0', '--max-candidate-calls', '0',
                   '--max-input-bytes', '0', '--candidate-producer', 'fixture/1',
                   '--candidate-command', sys.executable, str(self.script)]
        result = subprocess.run(command, text=True, capture_output=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('budget_reached', result.stdout)
        self.assertEqual(workspace.status(self.work)['provider_usage']['providers'], {})


if __name__ == '__main__': unittest.main()
