"""Replay actual /7 provider responses; preserve earlier failed experiments."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.evaluate_requirement_production import FIXTURES,prepared
from tracker import requirement_diagnostics as detector
from tracker.schema import digest
from tracker.semantic_extraction import read


class RequirementProductionLiveTests(unittest.TestCase):
    def test_exact_production_seven_replays_all_live_scans_and_reused_extractions(self):
        frozen=read(FIXTURES/'requirement-production-live.json')
        controls,rows=prepared()
        self.assertEqual(frozen['protocol'],detector.protocol(detector.CONFLICT_VERSION))
        self.assertEqual(frozen['primary_fixture_hash'],controls['primary_hash'])
        self.assertEqual(frozen['supplemental_fixture_hash'],controls['supplemental_hash'])
        self.assertEqual(frozen['reference_hash'],digest(controls['references']))
        self.assertEqual(frozen['original_reference_hash'],controls['original_reference_hash'])
        self.assertEqual(frozen['baseline_receipts_hash'],controls['baseline_receipts_hash'])
        self.assertEqual(frozen['supplemental_receipts_hash'],controls['supplemental_receipts_hash'])
        actual={row['case_id']:row for row in frozen['rows']};scan_count=0;extraction_count=0
        with TemporaryDirectory() as temp:
            for row in rows:
                saved=actual[row['case_id']]
                self.assertEqual(row['source_hash'],saved['source_hash'])
                self.assertEqual(set(row['extraction']),set(saved['reused_extraction_request_hashes']))
                scans={p['request_hash']:p for p in saved['scan_packets']}
                expected={digest(req):req for req in row['requests']};seen=set()
                def replay(request):
                    key=digest(request);self.assertEqual(request,expected[key]);seen.add(key)
                    if request['state']['stage']=='requirement_extraction':packet=row['extraction'][key]
                    else:
                        self.assertEqual(request['state']['harness'],detector.CONFLICT_VERSION)
                        self.assertEqual(request['state']['protocol_id'],frozen['protocol']['id'])
                        self.assertNotIn('development_requirement_arm',request['state'])
                        packet=scans[key]
                    self.assertEqual(digest(packet['response']),packet['response_hash'])
                    self.assertEqual(packet['response']['model'],request['model'])
                    return packet['response']
                directory=Path(temp)/row['case_id']
                result=detector.execute(row['source'],directory,replay,version=detector.CONFLICT_VERSION)
                self.assertEqual(seen,set(expected))
                self.assertEqual(digest(result),saved['result_hash'])
                self.assertEqual(result['metrics'][detector.METRIC]['value'],saved['prediction'])
                self.assertEqual(saved['prediction'] in saved['accepted_values'],saved['reference_match'])
                self.assertTrue(saved['reference_match'])
                self.assertTrue(detector.audit(row['source'],result,directory)['exact_replay'])
                self.assertEqual(detector.execute(row['source'],directory,lambda _:self.fail('Cached replay must not call transport')),result)
                scan_count+=len(scans);extraction_count+=len(row['extraction'])
        self.assertEqual((scan_count,extraction_count),(11,11))
        self.assertEqual(actual['encoded-completion-read']['prediction'],0)
        self.assertEqual(actual['opaque-implementation-insufficient']['prediction'],0)
        self.assertEqual(actual['contradicted-final-completion']['prediction'],1)
        self.assertEqual(frozen['saved_report_new_calls_this_invocation'],0)

    def test_previous_false_conflicts_remain_frozen_as_observed(self):
        baseline=read(FIXTURES/'requirement-harness-live.json')
        original={row['case_id']:row for row in baseline['rows']}
        self.assertEqual(original['encoded-completion-read']['prediction'],1)
        self.assertFalse(original['encoded-completion-read']['reference_match'])
        self.assertEqual(original['opaque-implementation-insufficient']['prediction'],1)
        self.assertFalse(original['opaque-implementation-insufficient']['reference_match'])
        intermediate=read(FIXTURES/'requirement-intermediate-live.json')
        row=next(r for r in intermediate['rows'] if r['case_id']=='encoded-completion-read')
        self.assertEqual(row['prediction'],1)
        selected=row['packets'][0]['selected_fragments']['requirement_0']
        self.assertEqual((selected['event_id'],selected['kind']),('e4','action'))


if __name__=='__main__':unittest.main()
