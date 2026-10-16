from itertools import product
import unittest

from tracker.repeated_sequences import find, source_measure
from tracker.schema import InputError


def oracle(tokens, limit=64):
    """Independent interval enumeration with a direct minimum-period check."""
    result = set()
    for start in range(len(tokens)):
        for end in range(start + 2, len(tokens) + 1):
            block = tokens[start:end]
            if None in block:
                continue
            period = next((p for p in range(1, len(block) // 2 + 1)
                           if all(block[i] == block[i - p] for i in range(p, len(block)))), None)
            if period is None or period > limit:
                continue
            if start and tokens[start - 1] == tokens[start + period - 1]:
                continue
            if end < len(tokens) and tokens[end] == tokens[end - period]:
                continue
            result.add((start, end, period))
    return result


class ConsecutivePatternTests(unittest.TestCase):
    def test_matches_independent_oracle_on_short_sequences_and_missingness(self):
        for alphabet, max_size in [(('a', 'b'), 8), (('a', 'b', None), 6)]:
            for size in range(max_size + 1):
                for values in product(alphabet, repeat=size):
                    tokens = list(values)
                    actual = {(r['start'], r['end'], r['period']) for r in find(tokens)['runs']}
                    self.assertEqual(actual, oracle(tokens), tokens)

    def test_multi_operation_repetition_and_partial_tail(self):
        result = find(list('xabcdabcdabcdabz'))
        self.assertEqual([(r['start'], r['end'], r['period'], r['full_copies'], r['partial_tail'])
                          for r in result['runs']], [(1, 15, 4, 3, 2)])
        self.assertEqual(result['repeated_positions'], list(range(5, 15)))

    def test_nested_period_aliases_do_not_duplicate_counts(self):
        result = find(list('aaaaaaaa'))
        self.assertEqual(len(result['runs']), 1)
        self.assertEqual(result['runs'][0]['period'], 1)
        self.assertEqual(result['repeated_positions'], list(range(1, 8)))
        overlapping = find(list('abaababaab'))
        indices = {i for r in overlapping['runs'] for i in range(r['start'] + r['period'], r['end'])}
        self.assertEqual(len(overlapping['repeated_positions']), len(indices))

    def test_missing_positions_are_barriers_and_bounds_include_bridging_known_tokens(self):
        result, measure, unknown = source_measure(['a', None, 'a', 'b'])
        self.assertEqual(result['runs'], [])
        self.assertEqual(measure, {'numerator': 0, 'denominator': 4, 'unknown': 3})
        self.assertEqual(unknown, [1, 2, 3])
        complete, measure, unknown = source_measure(['a', 'b', 'a', 'b'])
        self.assertEqual(measure, {'numerator': 2, 'denominator': 4, 'unknown': 0})
        self.assertEqual(unknown, [])
        self.assertEqual(find(['a', 'b', None, 'a', 'b'])['runs'], [])

    def test_configured_period_scope_is_explicit_and_inputs_unchanged(self):
        tokens = list('abcabc')
        result = find(tokens, max_period=2)
        self.assertEqual(tokens, list('abcabc'))
        self.assertEqual(result['runs'], [])
        self.assertEqual(result['considered_period'], 2)
        self.assertEqual(find(tokens), find(tokens))
        for bad in [0, -1, True, 1025, '2']:
            with self.assertRaises(InputError):
                find(tokens, max_period=bad)
        with self.assertRaises(InputError):
            find(['a', ''])

    def test_missingness_bounds_contain_every_binary_completion(self):
        for values in product(('a', 'b', None), repeat=5):
            tokens = list(values)
            _, measure, _ = source_measure(tokens)
            missing = [i for i, token in enumerate(tokens) if token is None]
            for replacements in product(('a', 'b'), repeat=len(missing)):
                completed = list(tokens)
                for i, value in zip(missing, replacements):
                    completed[i] = value
                actual = len(find(completed)['repeated_positions'])
                self.assertLessEqual(measure['numerator'], actual, tokens)
                self.assertGreaterEqual(measure['numerator'] + measure['unknown'], actual, tokens)


if __name__ == '__main__':
    unittest.main()
