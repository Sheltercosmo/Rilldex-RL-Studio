from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tests.test_work_declarations import fixture
from tracker.schema import InputError, digest
from tracker.declared_work_items import proposal_request, validate, selection_request, inspect, FileCandidates, DESCRIBED_VERSION


class DeclaredWorkItemTests(unittest.TestCase):
    def test_one_orient_can_hold_a_reported_outcome_and_distinct_undertaking(self):
        run, doc = fixture(['Pandoc is installed. I will convert the report.'])
        unit = doc['units'][0]; before = deepcopy(unit); proposal = proposal_request(run, doc, unit)
        response = {'request_hash': digest(proposal), 'producer': 'authored-test', 'candidates': [{'items': [
            {'id': 'installed', 'work': 'Install Pandoc.', 'declaration': 'reports_finished', 'evidence': [unit['source']]},
            {'id': 'convert', 'work': 'Convert the report to PDF.', 'declaration': 'commits', 'evidence': [unit['source']]}]}]}
        items = validate(run, proposal, response)[0]['items']
        self.assertEqual(len(items), 2)
        self.assertEqual(unit, before)
        self.assertEqual(unit['activity'], 'orient')
        self.assertEqual(selection_request(run, proposal, response)['state']['unit_activity'], 'orient')

    def test_missing_candidates_is_not_an_empty_selected_bundle(self):
        run, doc = fixture(['The exchange is pending.']); unit = doc['units'][0]
        with TemporaryDirectory() as folder:
            result = inspect(run, doc, unit, FileCandidates(folder), None)
            self.assertEqual(result['status'], 'needs_candidates')
            self.assertEqual(len(list((Path(folder) / 'requests').glob('*.json'))), 1)
        proposal = proposal_request(run, doc, unit)
        response = {'request_hash': digest(proposal), 'producer': 'authored-test', 'candidates': [{'items': []}]}
        self.assertEqual(validate(run, proposal, response), [{'items': []}])

    def test_future_old_only_and_unsupported_state_are_rejected(self):
        run, doc = fixture(['I will write A.', 'A is done.']); early, late = doc['units']
        for problem in ['future', 'old-only', 'verified-state', 'duplicate']:
            with self.subTest(problem=problem):
                unit = early if problem == 'future' else late
                proposal = proposal_request(run, doc, unit)
                item = {'id': 'work', 'work': 'Write A.', 'declaration': 'reports_finished', 'evidence': [unit['source']]}
                if problem == 'future': item['evidence'] = [late['source']]
                if problem == 'old-only': item['evidence'] = [early['source']]
                if problem == 'verified-state': item['declaration'] = 'verified_complete'
                response = {'request_hash': digest(proposal), 'producer': 'authored-test', 'candidates': [{'items': [item]}]}
                if problem == 'duplicate': response['candidates'][0]['items'].append(deepcopy(item))
                with self.assertRaises(InputError): validate(run, proposal, response)

    def test_other_source_actor_or_unit_cannot_be_silently_substituted(self):
        run, doc = fixture(['I will write A.']); unit = deepcopy(doc['units'][0]); unit['actor'] = 'user'
        with self.assertRaises(InputError): proposal_request(run, doc, unit)
        with self.assertRaises(InputError): proposal_request(run, {**doc, 'source_hash': 'different'}, doc['units'][0])

    def test_described_empty_bundle_retains_interpretation_and_version_boundary(self):
        run, doc = fixture(['Could you provide your user ID?']); unit = doc['units'][0]
        proposal = proposal_request(run, doc, unit, version=DESCRIBED_VERSION)
        reading = 'Requests information without announcing a separate own-work undertaking.'
        response = {'request_hash': digest(proposal), 'producer': 'authored-test',
                    'candidates': [{'items': [], 'reading': reading}]}
        self.assertEqual(validate(run, proposal, response)[0]['reading'], reading)
        req = selection_request(run, proposal, response)
        self.assertEqual(req['state']['candidate_bundles'], response['candidates'])
        for bad in [None, '', ' ', 'a' * 1601]:
            with self.subTest(reading=repr(bad)[:30]):
                invalid = deepcopy(response)
                if bad is None: del invalid['candidates'][0]['reading']
                else: invalid['candidates'][0]['reading'] = bad
                with self.assertRaises(InputError): validate(run, proposal, invalid)
        old_proposal = proposal_request(run, doc, unit)
        old_response = {'request_hash': digest(old_proposal), 'producer': 'authored-test',
                        'candidates': [{'items': []}]}
        self.assertEqual(validate(run, old_proposal, old_response), [{'items': []}])
        old_response['candidates'][0]['reading'] = reading
        with self.assertRaises(InputError): validate(run, old_proposal, old_response)
