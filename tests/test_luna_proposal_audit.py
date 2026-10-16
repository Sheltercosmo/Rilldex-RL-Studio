import copy
import hashlib
from pathlib import Path
import tempfile
import unittest

from research.luna_proposal_audit import context_exposure, plan_batches, frozen_text, audit
from research.path_selection_audit import ROOT
from research.luna_path_proposals import validate_output
from tracker.schema import InputError


def job(key, source='one', cutoff=2, actor='main'):
    text = 'abcdef'[:cutoff]
    return dict(job_id=key, source_prefix=dict(question='question', response=text),
        subject=dict(trace_id=source, source_pointer='/response', actor_id=actor,
            start=cutoff-1, end=cutoff, text=text[-1:]), candidates=[])


class ProposalAuditTests(unittest.TestCase):
    def test_later_prefix_exposes_earlier_job_even_for_another_actor(self):
        rows = context_exposure([job('earlier'), job('later', cutoff=5, actor='other')])
        self.assertEqual(rows[0]['excess_characters'], 3)
        self.assertEqual(rows[0]['later_jobs'], ['later'])
        self.assertEqual(rows[1]['excess_characters'], 0)

    def test_independent_sources_and_equal_prefixes_can_share(self):
        jobs = [job('a'), job('b'), job('c', source='two', cutoff=5)]
        self.assertTrue(all(r['excess_characters']==0 for r in context_exposure(jobs)))
        self.assertEqual(plan_batches(jobs), [['a','b','c']])

    def test_planned_batches_cover_once_without_future_exposure(self):
        jobs = [job('a'), job('b', cutoff=3), job('c', cutoff=5), job('d', source='two', cutoff=6)]
        batches = plan_batches(jobs)
        self.assertEqual(len(batches), 3)
        self.assertEqual(sorted(x for b in batches for x in b), ['a','b','c','d'])
        for ids in batches:
            self.assertTrue(all(r['excess_characters']==0 for r in context_exposure([j for j in jobs if j['job_id'] in ids])))
        self.assertEqual(batches, plan_batches(list(reversed(jobs))))

    def test_prefix_conflicts_fail_even_if_each_subject_is_valid(self):
        for field, value in [('question','other question'), ('response','zbcde')]:
            later = job('b', cutoff=5)
            later['source_prefix'][field] = value
            with self.subTest(field=field), self.assertRaises(InputError):
                context_exposure([job('a'), later])

    def test_duplicate_job_and_inexact_cutoff_rejected(self):
        with self.assertRaises(InputError): context_exposure([job('a'), job('a')])
        bad = job('a'); bad['subject']['end'] = 1
        with self.assertRaises(InputError): context_exposure([bad])

    def test_candidate_must_be_earlier_and_exact(self):
        current = job('a', cutoff=5)
        unit = dict(trace_id='one', source_pointer='/response', start=0, end=2, text='ab')
        current['candidates'] = [dict(candidate_id='c0', unit=unit)]
        context_exposure([current])
        for field, value in [('end',5), ('text','invented'), ('trace_id','another')]:
            bad = copy.deepcopy(current); bad['candidates'][0]['unit'][field] = value
            with self.subTest(field=field), self.assertRaises(InputError): context_exposure([bad])

    def test_crlf_transport_is_audited_without_rewriting_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'source.txt'
            path.write_bytes(b'a\r\nb\r\n')
            text, receipt = frozen_text(path, hashlib.sha256(b'a\nb\n').hexdigest())
            self.assertEqual(text, 'a\nb\n')
            self.assertEqual(receipt['actual_bytes'],6)
            self.assertEqual(receipt['lf_bytes'],4)
            self.assertEqual(path.read_bytes(), b'a\r\nb\r\n')
            path.write_bytes(b'a\r\nc\r\n')
            with self.assertRaises(InputError): frozen_text(path, hashlib.sha256(b'a\nb\n').hexdigest())

    def test_instruction_candidate_uses_its_own_source_and_event_order(self):
        current = job('a'); current['subject']['event_index'] = 1
        unit = dict(trace_id='one', source_pointer='/raw_text/question',
            event_index=0, start=0, end=8, text='question')
        current['candidates'] = [dict(candidate_id='c0', unit=unit)]
        context_exposure([current])
        unit['event_index'] = 2
        with self.assertRaises(InputError): context_exposure([current])

    def test_missing_output_job_is_not_a_negative(self):
        with self.assertRaises(InputError):
            validate_output(dict(jobs=[job('a')]), dict(schema='luna-path-proposal/1', variant='baseline', jobs=[]), 'baseline')

    def test_retained_experiment_has_two_variants_and_exposure_limit(self):
        result = audit(ROOT/'research/luna-purpose-target-2026-10-11')
        self.assertEqual(result['status'], 'exploratory_not_promoted')
        self.assertEqual(len(result['reports']),2)
        self.assertEqual(sum(bool(r['excess_characters']) for r in result['reports'][0]['context_exposure']),4)
        self.assertEqual(len(result['safe_future_batches']),4)
        self.assertIsNone(result['usage']['billed_tokens'])
        self.assertEqual(result['usage']['jev_calls'],0)


if __name__ == '__main__': unittest.main()
