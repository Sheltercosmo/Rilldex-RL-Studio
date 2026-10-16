import unittest
from tracker import distribution_readiness as d


class AvailabilityTests(unittest.TestCase):
    def test_delay_keeps_timezones_and_unknown_timestamps_separate(self):
        self.assertEqual(d.delay('2026-10-16T11:00:00+01:00','2026-10-16T10:00:12Z'),12)
        for a,b in [(None,None),('bad','bad'),('2026-10-16','2026-10-17'),('2026-10-16T11:00:00Z','2026-10-16T10:00:00Z')]:
            self.assertIsNone(d.delay(a,b))

    def test_empty_population_has_no_zero_coverage_or_latency_claim(self):
        s=d.summarize([])
        self.assertIsNone(s['coverage']);self.assertIsNone(s['delay']['median_seconds'])
        self.assertEqual(s['population'],0)

    def test_available_empty_and_missing_inputs_have_distinct_denominators(self):
        rows=[dict(status=status,capture_state='complete',task_id='a',policy_version=None,
                   local_availability_delay_seconds=seconds) for status,seconds in [('available',2),('no_opportunities',8),('not_observed',None)]]
        s=d.summarize(rows)
        self.assertEqual((s['current'],s['eligible'],s['no_opportunities']),(2,1,1))
        self.assertEqual(s['coverage'],2/3);self.assertEqual(s['delay']['median_seconds'],5)
        self.assertEqual(s['selection'][0]['groups'][0]['measured'],1)
        self.assertIn('not model inference latency',s['delay']['definition'])


if __name__=='__main__':unittest.main()
