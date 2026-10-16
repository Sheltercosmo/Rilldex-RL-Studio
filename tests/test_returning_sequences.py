from itertools import product
import unittest

from tracker.returning_sequences import find, MAX_POSITIONS
from tracker.schema import InputError


def oracle(tokens, maximum=64):
    """Enumerate every word and its occurrences, independently of suffix sorting."""
    words = {}
    for start in range(len(tokens)):
        for end in range(start + 2, min(len(tokens), start + maximum) + 1):
            word = tuple(tokens[start:end])
            if None not in word and len(set(word)) > 1:
                words.setdefault(word, []).append(start)
    output = {}
    for word, starts in words.items():
        length = len(word)
        if len(starts) < 2:
            continue
        if length < maximum:
            left = {tokens[s - 1] if s and tokens[s - 1] is not None else ('left', s) for s in starts}
            right = {tokens[s + length] if s + length < len(tokens) and tokens[s + length] is not None else ('right', s) for s in starts}
            if len(left) == 1 or len(right) == 1:
                continue
        pairs = []
        for current in starts:
            earlier = [s for s in starts if s + length <= current]
            if not earlier:
                continue
            previous = max(earlier)
            if previous + length == current:
                continue
            # Brute-force periodic covering intervals, without the production
            # periodic scanner or its prefix coverage array.
            covered = False
            for lo in range(previous + 1):
                for hi in range(current + length, len(tokens) + 1):
                    block = tokens[lo:hi]
                    if None not in block and any(all(block[i] == block[i - p] for i in range(p, len(block)))
                                                 for p in range(1, min(maximum, len(block) // 2) + 1)):
                        covered = True
            if not covered:
                pairs.append((previous, current))
        if pairs:
            output[word] = (starts, pairs)
    return output


def compact(result):
    return {tuple(p['pattern']): (p['starts'], [(r['previous_start'], r['current_start']) for r in p['returns']])
            for p in result['patterns']}


class ReturningSequenceTests(unittest.TestCase):
    def test_suffix_scan_matches_independent_word_oracle(self):
        for alphabet, max_size in [(('a', 'b'), 9), (('a', 'b', None), 7)]:
            for size in range(max_size + 1):
                for values in product(alphabet, repeat=size):
                    tokens = list(values)
                    self.assertEqual(compact(find(tokens)), oracle(tokens), tokens)

    def test_intervening_work_and_missing_gaps_are_retained(self):
        tokens = ['outbound', 'return', 'calculate', None, 'account', 'outbound', 'return']
        result = find(tokens)['patterns']
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['starts'], [0, 5])
        self.assertEqual(result[0]['returns'][0]['missing_gap_positions'], [3])
        self.assertEqual(result[0]['returns'][0]['gap_start'], 2)
        self.assertEqual(result[0]['returns'][0]['gap_end'], 5)
        self.assertEqual(find(['outbound', None, 'return', 'outbound', 'return'])['patterns'], [])

    def test_periodic_copies_do_not_become_separated_return_counts(self):
        self.assertEqual(find(list('abababababab'))['patterns'], [])
        result = find(list('ababxabab'))['patterns']
        word = next(p for p in result if p['pattern'] == list('abab'))
        self.assertEqual([(r['previous_start'], r['current_start']) for r in word['returns']], [(0, 5)])
        self.assertFalse(any(p['pattern'] == ['b', 'a', 'b'] for p in result))

    def test_overlap_uses_nearest_disjoint_reference_without_erasing_occurrences(self):
        tokens = list('ababaxaba')
        result = find(tokens)['patterns']
        row = next(p for p in result if p['pattern'] == list('aba'))
        self.assertEqual(row['starts'], [0, 2, 6])
        self.assertEqual([(r['previous_start'], r['current_start']) for r in row['returns']], [(2, 6)])

    def test_length_scope_and_budget_are_explicit(self):
        tokens = list('abcdxabcd')
        self.assertEqual(compact(find(tokens, max_length=2)), oracle(tokens, 2))
        self.assertTrue(all(p['at_length_limit'] for p in find(tokens, max_length=2)['patterns']))
        self.assertEqual(find(['x'] * (MAX_POSITIONS + 1))['status'], 'requires_segment_selection')
        for limit in [1, True, 1025, '2']:
            with self.assertRaises(InputError):
                find(tokens, max_length=limit)


if __name__ == '__main__':
    unittest.main()
