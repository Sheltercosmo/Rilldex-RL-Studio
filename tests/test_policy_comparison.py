import math
import random
import unittest

from rilldex import compare_probabilities
from tracker.schema import InputError


class PolicyComparisonTests(unittest.TestCase):
    def test_probability_and_ratio_rules_disagree_in_both_directions(self):
        result = compare_probabilities([math.log(.01), math.log(.9)],
            [math.log(.06), math.log(.2)], [1, 1], probability_thresholds=[.2, .3], ratio_bounds=[.2, 5])
        self.assertAlmostEqual(result['mean_probability_gap'], .375)
        self.assertAlmostEqual(result['p95_probability_gap'], .7)
        self.assertEqual(result['ratio']['excluded_tokens'], 1)
        for rule in result['thresholds']:
            self.assertEqual(rule['excluded_fraction'], .5)
            self.assertEqual(rule['probability_only_tokens'], 1)
            self.assertEqual(rule['ratio_only_tokens'], 1)
            self.assertEqual(rule['disagreement_fraction'], 1)

    def test_random_rules_match_independent_probability_calculation(self):
        rng = random.Random(19)
        a = [rng.uniform(.0001, .9999) for _ in range(300)]
        b = [rng.uniform(.0001, .9999) for _ in a]
        mask = [i % 3 != 0 for i in range(len(a))]
        result = compare_probabilities(map(math.log, a), map(math.log, b), mask,
            probability_thresholds=[0, .1, .2, .8, 1], ratio_bounds=[.2, 5])
        pairs = [(p, q) for p, q, use in zip(a, b, mask) if use]
        for rule in result['thresholds']:
            want = [abs(p-q) > rule['threshold'] for p, q in pairs]
            ratios = [q/p < .2 or q/p > 5 for p, q in pairs]
            self.assertEqual(rule['excluded_tokens'], sum(want))
            self.assertEqual(rule['probability_only_tokens'], sum(p and not r for p, r in zip(want, ratios)))
            self.assertEqual(rule['ratio_only_tokens'], sum(r and not p for p, r in zip(want, ratios)))
        self.assertEqual(result['compared_tokens'], 200)

    def test_empty_mask_underflow_extremes_and_tiny_differences(self):
        empty = compare_probabilities([float('nan')], [None], [0], probability_thresholds=[.3], ratio_bounds=[.2, 5])
        self.assertIsNone(empty['mean_probability_gap'])
        self.assertIsNone(empty['thresholds'][0]['excluded_fraction'])
        self.assertEqual(empty['compared_tokens'], 0)
        extreme = compare_probabilities([-10000., -10000.], [0., -9999.], [1, 1])
        self.assertEqual(extreme['max_probability_gap'], 1.)
        self.assertEqual(extreme['token_weight_ess_fraction'], .5)
        small = compare_probabilities([-.1], [-.1 + 1e-12], [1])
        self.assertGreater(small['max_probability_gap'], 0)
        identity = compare_probabilities([-.1], [-.1], [1], probability_thresholds=[0], ratio_bounds=[1, 1])
        self.assertEqual(identity['ratio']['excluded_fraction'], 0)
        self.assertEqual(identity['thresholds'][0]['excluded_fraction'], 0)

    def test_invalid_probabilities_and_rules_are_rejected(self):
        for a, b, mask in [([1.], [1.], [1]), ([float('inf')], [-1.], [1]),
                           ([-1], [-2], [2]), ([-1], [], [1])]:
            with self.assertRaises(InputError):
                compare_probabilities(a, b, mask)
        for kwargs in [dict(probability_thresholds=[float('nan')]), dict(probability_thresholds=[-.1]),
                       dict(probability_thresholds=[.2]*17), dict(ratio_bounds=[0, 5]),
                       dict(ratio_bounds=[5, .2]), dict(ratio_bounds=[1, float('inf')])]:
            with self.assertRaises(InputError):
                compare_probabilities([-1], [-2], [1], **kwargs)


if __name__ == '__main__':
    unittest.main()
