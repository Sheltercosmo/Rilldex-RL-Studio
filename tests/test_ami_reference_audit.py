"""Reference integrity and temporal retrieval tests, not semantic accuracy tests."""
import copy
import json
from pathlib import Path
import unittest

from research.ami_reference_audit import parse_meeting, candidates, audit_meeting, reference_pack, run


def fixture():
    ns = 'xmlns:nite="http://nite.sourceforge.net/"'
    root = lambda content: ('<?xml version="1.0" encoding="UTF-8"?><nite:root ' + ns + '>' + content + '</nite:root>').encode()
    members = {
        'ontologies/da-types.xml': root('<type nite:id="inf" name="inf" gloss="Inform"/>'),
        'ontologies/ap-types.xml': root('<type nite:id="pos" name="POS" gloss="Support"/>'),
        'words/M.A.words.xml': root('<w nite:id="w0" starttime="1" endtime="2">café</w>'
                                   '<vocalsound nite:id="w9" starttime="2" endtime="2" type="laugh"/>'
                                   '<w nite:id="w3" starttime="2" endtime="3">😀</w>'),
        'words/M.B.words.xml': root('<w nite:id="b0" starttime="4" endtime="5">Yes</w>'),
        'words/M.C.words.xml': root(''), 'words/M.D.words.xml': root(''),
        'dialogueActs/M.A.dialog-act.xml': root('<dact nite:id="a"><nite:pointer role="da-aspect" href="da-types.xml#id(inf)"/>'
                                              '<nite:child href="M.A.words.xml#id(w0)..id(w3)"/></dact>'),
        'dialogueActs/M.B.dialog-act.xml': root('<dact nite:id="b"><nite:child href="M.B.words.xml#id(b0)"/></dact>'),
        'dialogueActs/M.C.dialog-act.xml': root(''), 'dialogueActs/M.D.dialog-act.xml': root(''),
        'dialogueActs/M.adjacency-pairs.xml': root('<adjacency-pair nite:id="p"><nite:pointer role="source" href="M.A.dialog-act.xml#id(a)"/>'
                                                 '<nite:pointer role="target" href="M.B.dialog-act.xml#id(b)"/>'
                                                 '<nite:pointer role="type" href="ap-types.xml#id(pos)"/></adjacency-pair>'
                                                 '<adjacency-pair nite:id="missing"><nite:pointer role="target" href="M.B.dialog-act.xml#id(b)"/>'
                                                 '<nite:pointer role="type" href="ap-types.xml#id(pos)"/></adjacency-pair>')}
    return members


class AMIReferenceTests(unittest.TestCase):
    def test_exact_range_uses_document_order_and_preserves_nonwords_unicode(self):
        data = parse_meeting(fixture().__getitem__, 'M'); a, b = data['units']
        self.assertEqual(a['token_ids'], ['w0', 'w9', 'w3'])
        self.assertEqual(a['text'], 'café [vocalsound:laugh] 😀')
        self.assertEqual((a['start'], a['end']), (1, 3))
        self.assertEqual(b['actor'], 'B')
        self.assertNotIn('types', a)
        self.assertFalse(data['native_acts'][0]['product_reference'])

    def test_missing_annotations_do_not_create_negative_references(self):
        data = parse_meeting(fixture().__getitem__, 'M'); report = audit_meeting(data)
        self.assertEqual(report['summary']['missing_act_types'], 1)
        self.assertEqual(report['summary']['missing_source_links'], 1)
        self.assertEqual(report['summary']['eligibility'], {'eligible_at_target_end': 1, 'missing_or_multiple_endpoints_or_type': 1})
        self.assertTrue(all(r['eligible_native_links'] == 1 for r in report['coverage']))
        self.assertEqual(data['native_links'][1]['source'], [])

    def test_bad_pointer_wrong_document_reverse_range_and_duplicate_id_fail(self):
        edits = [('dialogueActs/M.A.dialog-act.xml', b'id(w0)..id(w3)', b'id(w0)..id(absent)'),
                 ('dialogueActs/M.A.dialog-act.xml', b'M.A.words.xml', b'M.B.words.xml'),
                 ('dialogueActs/M.A.dialog-act.xml', b'id(w0)..id(w3)', b'id(w3)..id(w0)'),
                 ('words/M.A.words.xml', b'nite:id="w3"', b'nite:id="w0"'),
                 ('dialogueActs/M.adjacency-pairs.xml', b'M.A.dialog-act.xml#id(a)', b'M.B.dialog-act.xml#id(a)')]
        for filename, old, new in edits:
            with self.subTest(filename=filename, new=new):
                files = fixture(); files[filename] = files[filename].replace(old, new)
                with self.assertRaises(ValueError): parse_meeting(files.__getitem__, 'M')

    def test_invalid_time_and_overlapping_source_are_not_backfilled(self):
        files = fixture(); files['words/M.A.words.xml'] = files['words/M.A.words.xml'].replace(b'endtime="3"', b'endtime="9"')
        data = parse_meeting(files.__getitem__, 'M'); a, b = data['units']
        self.assertEqual(candidates(data['units'], b, 20), [])
        report = audit_meeting(data)
        self.assertEqual(report['links'][0]['eligibility'], 'source_extends_beyond_target_cutoff')
        files = fixture(); files['words/M.A.words.xml'] = files['words/M.A.words.xml'].replace(b'endtime="3"', b'endtime="1"')
        data = parse_meeting(files.__getitem__, 'M')
        self.assertFalse(data['units'][0]['time_available'])
        self.assertEqual(audit_meeting(data)['links'][0]['eligibility'], 'missing_endpoint_time')

    def test_retrieval_is_cross_actor_label_blind_and_cutoff_bound(self):
        data = parse_meeting(fixture().__getitem__, 'M'); a, b = data['units']
        expected = candidates(data['units'], b, 20)
        self.assertEqual([u['id'] for u in expected], ['a'])
        enriched = copy.deepcopy(data['units'])
        for u in enriched: u.update(native_type='secret', reference='secret', reward=1, confidence=1)
        enriched += [{**a, 'id': 'future', 'start': 6, 'end': 7}, {**a, 'id': 'different', 'meeting': 'N'}]
        self.assertEqual(candidates(enriched, b, 20), expected)
        overlap = {**a, 'id': 'overlap', 'start': 4, 'end': 4.5}
        self.assertEqual([u['id'] for u in candidates([a, overlap], b, 20, 'start')], ['a'])
        self.assertEqual([u['id'] for u in candidates([a, overlap], b, 20, 'end')], ['overlap', 'a'])

    def test_frozen_real_sources_reconcile_without_rewriting(self):
        root = Path(__file__).resolve().parents[1] / 'research/ami-source-audit-2026-10-07'
        path = root / 'derived/audit.json'; before = path.read_bytes()
        result = run(root)
        self.assertEqual(result, json.loads(before))
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(sum(m['summary']['units'] for m in result['meetings']), 1133)
        self.assertEqual(sum(m['summary']['missing_source_links'] for m in result['meetings']), 34)

    def test_multiple_native_sources_remain_distinct_and_references_stay_out_of_cases(self):
        data = parse_meeting(fixture().__getitem__, 'M')
        source = {**data['units'][0], 'id': 'c', 'actor': 'C', 'start': 3, 'end': 4}
        data['units'].append(source)
        data['native_links'].append({**data['native_links'][0], 'id': 'p2', 'source': ['c']})
        report = audit_meeting(data); cases, refs, coverage = reference_pack(data, report)
        self.assertEqual(len(cases), 1)
        self.assertEqual({r['source_id'] for r in refs[0]['positives']}, {'a', 'c'})
        self.assertFalse(refs[0]['negative_links_available'])
        self.assertEqual(len(refs[0]['other_incoming_native_links']), 1)
        self.assertEqual(coverage[0]['at_least_one_eligible_annotated_source_retained'], 1)
        self.assertEqual(coverage[0]['all_eligible_annotated_sources_retained'], 0)
        text = json.dumps(cases)
        for forbidden in ('native_types', 'native_acts', 'native_links', 'positives', 'product_reference'):
            self.assertNotIn(forbidden, text)


if __name__ == '__main__': unittest.main()
