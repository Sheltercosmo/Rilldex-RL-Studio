"""Model-free checks for exact, source-bound candidate cache reuse."""
from pathlib import Path
import tempfile
import unittest

from tracker import candidate_cache
from tracker.schema import InputError, digest
from tracker.semantic_extraction import FileCandidates, generation_request, read, windows, write
from tests.test_semantic_extraction import fixture, proposals


class CandidateCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.request = {'schema': 'fixture-request/1', 'source': {'id': 'source-a'}, 'question': 'exact'}
        self.key = digest(self.request)
        self.response = {'request_hash': self.key, 'producer': 'fixture-generator/1',
            'candidates': [{'proposal': 'source-bound'}]}

    def cache_at(self, directory, *, request=None, response=None):
        folder = Path(directory) / 'candidates'
        write(folder / 'requests' / f'{self.key}.json', self.request if request is None else request)
        write(folder / 'responses' / f'{self.key}.json', self.response if response is None else response)
        return folder

    def test_exact_hit_copies_response_and_writes_reuse_receipt(self):
        source = self.root / 'source'
        self.cache_at(source)
        destination = self.root / 'destination' / 'candidates'
        self.assertTrue(candidate_cache.reuse(destination, self.request, [source]))
        self.assertEqual(read(destination / 'responses' / f'{self.key}.json'), self.response)
        receipt = read(destination / 'reuse' / f'{self.key}.json')
        self.assertEqual(receipt['schema'], candidate_cache.VERSION)
        self.assertEqual(receipt['request_hash'], self.key)
        self.assertEqual(receipt['response_hash'], digest(self.response))
        self.assertEqual(receipt['compatible_sources'], 1)
        self.assertEqual(receipt['new_candidate_calls'], 0)

    def test_changed_request_is_a_cache_miss(self):
        source = self.root / 'source'
        self.cache_at(source)
        changed = {**self.request, 'question': 'changed'}
        self.assertFalse(candidate_cache.reuse(self.root / 'destination' / 'candidates', changed, [source]))

    def test_wrong_saved_request_or_response_binding_is_rejected(self):
        source = self.root / 'source'
        wrong_request = self.cache_at(source, request={**self.request, 'question': 'wrong'})
        with self.assertRaisesRegex(InputError, 'binding differs'):
            candidate_cache.reuse(self.root / 'out-a' / 'candidates', self.request, [source])
        # Restore the exact request, then corrupt only the response binding.
        write(wrong_request / 'requests' / f'{self.key}.json', self.request)
        write(wrong_request / 'responses' / f'{self.key}.json', {**self.response, 'request_hash': 'wrong'})
        with self.assertRaisesRegex(InputError, 'binding differs'):
            candidate_cache.reuse(self.root / 'out-b' / 'candidates', self.request, [source])

    def test_conflicting_exact_source_proposals_are_rejected(self):
        self.cache_at(self.root / 'source-a')
        self.cache_at(self.root / 'source-b', response={**self.response,
            'candidates': [{'proposal': 'different'}]})
        with self.assertRaisesRegex(InputError, 'conflicting proposals'):
            candidate_cache.reuse(self.root / 'destination' / 'candidates', self.request,
                [self.root / 'source-a', self.root / 'source-b'])
        self.assertFalse((self.root / 'destination' / 'candidates' / 'responses' / f'{self.key}.json').exists())

    def test_existing_destination_is_never_overwritten(self):
        self.cache_at(self.root / 'source')
        destination = self.root / 'destination' / 'candidates'
        different = {'request_hash': self.key, 'producer': 'local-generator/2', 'candidates': ['existing']}
        write(destination / 'responses' / f'{self.key}.json', different)
        self.assertFalse(candidate_cache.reuse(destination, self.request, [self.root / 'source']))
        self.assertEqual(read(destination / 'responses' / f'{self.key}.json'), different)

    def test_file_candidates_still_validates_reused_payload(self):
        run = fixture(); ref = windows(run)[0]
        request = generation_request(run, ref, 'orient')
        key = digest(request)
        response = proposals(request)
        source = self.root / 'source'
        folder = source / 'candidates'
        write(folder / 'requests' / f'{key}.json', request)
        write(folder / 'responses' / f'{key}.json', {**response, 'candidates': []})
        provider = FileCandidates(self.root / 'destination' / 'candidates', cache_directories=[source])
        with self.assertRaisesRegex(InputError, 'Expected 1–3 content bundles'):
            provider.content(run, ref, 'orient')
        # The bad response is reused as a proposal file, but normal stage validation rejects it.
        self.assertTrue((self.root / 'destination' / 'candidates' / 'reuse' / f'{key}.json').exists())


if __name__ == '__main__':
    unittest.main()
