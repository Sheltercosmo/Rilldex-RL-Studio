"""Exact linked excerpts; retrieval checks do not establish detector accuracy."""
import json
import unittest
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory

from tracker import diagnostic_relations as relations, diagnostic_search as search, diagnostic_direct as direct
from tracker.schema import dumps
from test_diagnostic_monitors import source
from tracker import diagnostic_worker as worker
from tracker.adapters import normalize
from tracker.store import Store
from tracker.semantic_extraction import read
from test_tracker import harbor
from test_diagnostic_direct import wire


def fixture():
    text='ordinary log line\n'*1500+'\nexpected_output checksum mismatch: α != β\n'+'ordinary log line\n'*1500
    rows=[{'id':'a','actor':'agent','kind':'action','trajectory_id':'A','call_id':'one','tool':'read','text':'Read result file.'},
          {'id':'f','actor':'environment','kind':'feedback','trajectory_id':'A','source_call_id':'one','text':text}]
    s=source(trace=dumps(rows));fs=search.index(s,search.SCOPED_VERSION)
    return s,[f for f in fs if f.get('event_id')=='a']


class LinkedEvidenceTests(unittest.TestCase):
    def test_middle_evidence_is_recovered_within_the_existing_supplement_budget(self):
        from tracker import diagnostic_linked_evidence as linked
        s,fs=fixture();old=relations.packet(s,fs)
        self.assertTrue(old['omitted_linked_record_ids']);self.assertFalse(old['linked_source_records'])
        p=linked.packet(s,fs,queries=['expected output checksum mismatch'])
        self.assertTrue(any('α != β' in e['text'] for e in p['linked_source_excerpts']))
        self.assertLessEqual(p['linked_evidence_chars'],relations.LINK_LIMIT)
        self.assertTrue(p['partial_linked_record_ids']);self.assertFalse(p['unrepresented_linked_record_ids'])

    def test_excerpts_bind_to_exact_decoded_source_fields(self):
        from tracker import diagnostic_linked_evidence as linked
        s,fs=fixture();p=linked.packet(s,fs,queries=['checksum mismatch'])
        for e in p['linked_source_excerpts']:
            span=e['source_record'];obj=json.loads(s['trace'][span['start']:span['end']])
            for key in e['field_path']:obj=obj[key]
            self.assertEqual(e['text'],obj[e['start']:e['end']])
            self.assertFalse(e['complete_record'])
        self.assertEqual(p,linked.packet(s,fs,queries=['checksum mismatch']))

    def test_only_the_recorded_partner_is_eligible(self):
        from tracker import diagnostic_linked_evidence as linked
        s,fs=fixture();rows=json.loads(s['trace'])
        rows.insert(1,{'id':'b','actor':'environment','kind':'feedback','trajectory_id':'B','source_call_id':'one','text':'B_ONLY checksum mismatch'})
        s=source(trace=dumps(rows));fs=[f for f in search.index(s,search.SCOPED_VERSION) if f.get('event_id')=='a']
        p=linked.packet(s,fs,queries=['checksum mismatch'])
        self.assertNotIn('B_ONLY',dumps(p))
        self.assertEqual({e['event_id'] for e in p['linked_source_excerpts']},{'f'})

    def test_insufficient_budget_keeps_missingness_explicit(self):
        from tracker import diagnostic_linked_evidence as linked
        s,fs=fixture()
        with patch.object(relations,'LINK_LIMIT',1):p=linked.packet(s,fs,queries=['checksum mismatch'])
        self.assertFalse(p['linked_source_excerpts']);self.assertTrue(p['unrepresented_linked_record_ids'])

    def test_two_large_returns_each_get_a_passage_before_deeper_results(self):
        from tracker import diagnostic_linked_evidence as linked
        s,_=fixture();rows=json.loads(s['trace']);rows.extend([{**rows[0],'id':'a2','call_id':'two'},
            {**rows[1],'id':'f2','source_call_id':'two','text':rows[1]['text'].replace('checksum','digest')}])
        s=source(trace=dumps(rows));fs=[f for f in search.index(s,search.SCOPED_VERSION) if f.get('kind')=='action']
        p=linked.packet(s,fs,queries=['checksum mismatch','digest mismatch'])
        self.assertEqual({e['event_id'] for e in p['linked_source_excerpts']},{'f','f2'})
        self.assertLessEqual(p['linked_evidence_chars'],relations.LINK_LIMIT)

    def test_structured_action_arguments_are_readable_without_double_encoding(self):
        from tracker import diagnostic_linked_evidence as linked
        code='print("普通 output")\n'*1500+'expected_output = checker_reference\n'
        rows=[{'id':'a','actor':'agent','kind':'action','call_id':'one','tool':'write','arguments':{'content':code},'text':dumps({'content':code})},
              {'id':'f','actor':'environment','kind':'feedback','source_call_id':'one','text':'written'}]
        s=source(trace=dumps(rows));fs=[f for f in search.index(s,search.SCOPED_VERSION) if f.get('event_id')=='f']
        p=linked.packet(s,fs,queries=['expected output checker reference'])
        self.assertTrue(any(e['field_path']==['arguments','content'] and 'checker_reference' in e['text'] for e in p['linked_source_excerpts']))

    def test_production_requests_keep_pages_options_and_citations_unchanged(self):
        s,_=fixture()
        before=list(direct.requests(s,search.SCOPED_VERSION))
        after=list(direct.requests(s,search.LINKED_VERSION))
        self.assertEqual(len(before),len(after))
        self.assertEqual(direct.definitions(search.SCOPED_VERSION),direct.definitions(search.LINKED_VERSION))
        for a,b in zip(before,after):
            for key in ('page','source_fragments','candidate_fragment_ids','context_fragment_ids','recorded_result_links'):
                self.assertEqual(a['state'][key],b['state'][key])
            for name in a['questions']:self.assertEqual(a['questions'][name]['criteria'],b['questions'][name]['criteria'])
            self.assertLessEqual(b['state']['linked_evidence_chars'],relations.LINK_LIMIT)
            self.assertLessEqual(len(dumps(b)),search.REQUEST_CHARS)
        self.assertTrue(any(r['state']['linked_source_excerpts'] for r in after))

    def test_large_content_without_readable_fields_stays_unrepresented(self):
        from tracker import diagnostic_linked_evidence as linked
        rows=[{'id':'a','actor':'agent','kind':'action','call_id':'one','text':'read'},
              {'id':'f','actor':'environment','kind':'feedback','source_call_id':'one','content':[{'type':'image','data':'x'*20000}]}]
        s=source(trace=dumps(rows));fs=[f for f in search.index(s,search.SCOPED_VERSION) if f.get('event_id')=='a']
        p=linked.packet(s,fs,queries=['image'])
        self.assertFalse(p['linked_source_excerpts']);self.assertTrue(p['unrepresented_linked_record_ids'])

    def test_worker_partial_scan_resume_publication_and_exact_replay(self):
        with TemporaryDirectory() as temp:
            root=Path(temp);store=Store(root/'db');run=normalize(harbor(),'harbor')[0]
            result=next(e for e in run['events'] if e['kind']=='feedback')
            result['text']='ordinary log line\n'*1700+'\nexpected_output checksum mismatch\n'+'ordinary log line\n'*1700
            store.add([run]);selector=worker.selection(run_ids=[run['id']]);seen=[];folder=root/'worker'
            def capture(req):seen.append(req);return wire(req)
            first=worker.execute(store,folder,capture,selector=selector,protocol_name='search',max_new_calls=1)
            self.assertEqual(first['coverage']['counts'],{'pending':1})
            self.assertEqual(first['protocol']['schema'],search.DEFAULT_VERSION)
            finished=worker.execute(store,folder,capture,selector=selector,protocol_name='search',max_new_calls=30)
            self.assertEqual(finished['coverage']['counts'],{'complete':1})
            self.assertTrue(any(r['state']['linked_source_excerpts'] for r in seen))
            self.assertTrue(worker.audit(store,folder)['runs'][0]['validation']['exact_replay'])
            result=read(next(folder.glob('runs/*/*/result.json')))
            self.assertTrue(result['coverage']['scan_complete'])
            again=worker.execute(store,folder,lambda _:self.fail('Cached result must not call provider'),selector=selector,protocol_name='search',max_new_calls=0)
            self.assertEqual(again['new_calls'],0)


if __name__=='__main__':unittest.main()
