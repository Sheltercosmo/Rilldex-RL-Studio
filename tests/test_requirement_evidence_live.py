"""Actual production8 receipts, including real fresh role extraction and misses."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.evaluate_requirement_evidence import expected_values
from tracker import requirement_diagnostics as detector
from tracker.jev import validate_answers
from tracker.schema import digest
from tracker.semantic_extraction import read

FIXTURE=Path(__file__).parent/'fixtures/requirement-evidence-live.json'


class RequirementEvidenceLiveTests(unittest.TestCase):
    def test_actual_receipts_and_scoring_correction_preserve_all_inputs(self):
        frozen=read(FIXTURE)
        self.assertEqual(frozen['protocol'],detector.protocol(detector.EVIDENCE_VERSION))
        self.assertEqual(digest(frozen['inputs']),frozen['input_hash'])
        self.assertEqual(digest(frozen['pre_scoring_inputs']),frozen['pre_scoring_inputs_hash'])
        self.assertEqual(frozen['actual_new_calls'],{'total':28,'role_extraction':5,'conflict_scan':23})
        self.assertEqual(frozen['saved_cache_replay_new_calls'],0)
        self.assertEqual(frozen['pre_scoring_report']['new_calls_this_invocation'],28)
        old=deepcopy(frozen['pre_scoring_inputs']);new=deepcopy(frozen['inputs'])
        for manifest in (old,new):
            for row in manifest['rows']:
                for field in ('kind','source_kind','role_basis'):row.pop(field,None)
        self.assertEqual(old,new)
        origins={};count=0
        for row in frozen['rows']:
            self.assertEqual(row['accepted_values'],expected_values(row['reference']))
            for packet in row['packets']:
                self.assertEqual(digest(packet['request']),packet['request_hash'])
                self.assertEqual(digest(packet['response']),packet['response_hash'])
                answers=validate_answers(packet['response'],packet['request'])
                saved=packet['answers']
                self.assertEqual({key:a['value'] for key,a in answers.items()},
                                 {key:a.get('value',a.get('selection')) for key,a in saved.items()})
                origins[packet['receipt_origin']]=origins.get(packet['receipt_origin'],0)+1;count+=1
        self.assertEqual(count,39)
        self.assertEqual(origins,{'reused_actual_6_extraction':11,'new_actual_6_extraction':5,'new_actual_8_scan':23})

    def test_all_fifteen_compact_sources_execute_audit_and_resume_exactly(self):
        frozen=read(FIXTURE);count=0
        for row in frozen['rows']:
            if row['kind']=='historical_witness':continue
            with self.subTest(case=row['case_id']),TemporaryDirectory() as directory:
                source=row['source'];self.assertEqual(digest(source),row['source_hash'])
                packets={p['request_hash']:p for p in row['packets']};seen=[]
                def replay(request):
                    key=digest(request);self.assertIn(key,packets)
                    self.assertEqual(request,packets[key]['request']);seen.append(key)
                    return packets[key]['response']
                result=detector.execute(source,directory,replay,version=detector.EVIDENCE_VERSION)
                self.assertEqual(set(seen),set(packets));self.assertEqual(digest(result),row['result_hash'])
                self.assertEqual(result['coverage'],row['coverage'])
                self.assertIn(result['metrics'][detector.METRIC]['value'],row['accepted_values'])
                self.assertEqual(detector.audit(source,result,directory),row['audit'])
                self.assertEqual(detector.execute(source,directory,lambda _:self.fail('Cached production8 replay must not call transport')),result)
                if row['case_id']=='completion-claim-incomplete-excerpt':
                    self.assertIsNone(result['metrics'][detector.METRIC]['value'])
                    self.assertEqual(result['coverage']['unverified_questions'],1)
                    self.assertEqual(len(result['coverage']['unverified_comparisons']),1)
                if row['case_id']=='visible-contradiction-incomplete-record':
                    self.assertFalse(result['coverage']['complete_recorded_text'])
                    self.assertEqual(result['metrics'][detector.METRIC]['value'],1)
                count+=1
        self.assertEqual(count,15)

    def test_historical_fixed_targets_and_public_authored_origins_stay_distinct(self):
        frozen=read(FIXTURE);rows=[row for row in frozen['rows'] if row['kind']=='historical_witness']
        self.assertEqual(len(rows),6)
        self.assertEqual(sum(row['source_kind']=='pinned_public_local_witness' for row in rows),4)
        self.assertEqual(sum(row['source_kind']=='prior_authored_contrast' for row in rows),2)
        self.assertEqual(sum(row['reference_match'] for row in rows),3)
        for row in rows:
            events=[];unknown=False
            for packet in row['packets']:
                for answer in validate_answers(packet['response'],packet['request']).values():
                    fragment=packet['request']['state']['source_fragments'].get(answer['value'],{})
                    if fragment.get('event_id'):events.append(fragment['event_id'])
                    unknown|=answer['value'] in {'unverified_claim','unresolved'}
            target=1 if set(events)&set(row['target_events']) else None if unknown else 0
            self.assertEqual(target,row['target_prediction'])
            self.assertEqual(target in expected_values(row['reference']),row['reference_match'])
            if row['case_id']=='lossy-compression':
                self.assertEqual(row['selected_event_ids'],['e107']);self.assertEqual(row['target_events'],['e111'])
                self.assertFalse(row['reference_match'])
            if row['case_id']=='helm-ordering':
                self.assertEqual(row['selected_event_ids'],['e565']);self.assertEqual(row['target_events'],['e567'])
                self.assertFalse(row['reference_match'])
            if row['case_id']=='httpx-json-bom':
                self.assertEqual(row['selected_event_ids'],[]);self.assertFalse(row['reference_match'])
            if row['source_kind']=='prior_authored_contrast':
                self.assertEqual(row['historical_role_packet_hashes'],[])
                self.assertEqual(row['role_basis'],'prior_authored_fixed_requirements')


if __name__=='__main__':unittest.main()
