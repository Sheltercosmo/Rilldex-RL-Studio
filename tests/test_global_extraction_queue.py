import tempfile
import unittest
from pathlib import Path

from scripts.run_global_extraction import pending_manifest
from tracker.schema import digest, InputError
from tracker.semantic_extraction import write


class GlobalExtractionQueueTests(unittest.TestCase):
    def test_rejected_existing_response_stays_queued_and_old_requests_do_not(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            req={'stage':'content','source':{'event_id':'e2'}};key=digest(req)
            rejected={'request_hash':key,'response':{'candidates':[]},'validation_error':'Empty content'}
            rejection=digest(rejected)
            write(root/'candidates/requests'/f'{key}.json',req)
            write(root/'candidates/responses'/f'{key}.json',rejected['response'])
            write(root/'candidates/rejections'/f'{rejection}.json',rejected)
            write(root/'candidates/requests/obsolete.json',{'stage':'old activity'})
            result={'run_id':'run1','windows':[], 'units':[{'id':'u2','source':req['source'],
                'status':'needs_candidate_repair','candidate_request':key,'candidate_rejection':rejection}]}
            value=pending_manifest(root,result)
            self.assertEqual(len(value['requests']),1)
            self.assertEqual(value['requests'][0]['request_hash'],key)
            self.assertEqual(value['requests'][0]['validation_error'],'Empty content')
            self.assertIn('response_file',value['requests'][0])
            result['units'][0]['status']='selected'
            self.assertEqual(pending_manifest(root,result)['requests'],[])

    def test_unresolved_stages_are_visible_without_fabricating_a_candidate_request(self):
        result={'run_id':'run1','windows':[{'id':'w1','source':{'event_id':'e1'},
            'status':'needs_partition_candidates','reason':'no_suitable_candidate'}],
            'units':[{'id':'u2','source':{'event_id':'e2'},'status':'needs_activity_review'}]}
        with tempfile.TemporaryDirectory() as d:
            value=pending_manifest(d,result)
            self.assertEqual(value['requests'],[])
            self.assertEqual([r['id'] for r in value['pending_reviews']],['w1','u2'])

    def test_raw_choice_rejection_returns_to_content_proposer(self):
        with tempfile.TemporaryDirectory() as d:
            req={'stage':'content','source':{'event_id':'e2'}};key=digest(req)
            write(Path(d)/'candidates/requests'/f'{key}.json',req)
            result={'run_id':'run1','windows':[],'units':[{'id':'u2','source':req['source'],
                'status':'needs_content_repair','candidate_request':key,
                'content_choice':'no_suitable_candidate','content_request':'decision1'}]}
            entry=pending_manifest(d,result)['requests'][0]
            self.assertEqual(entry['selection'],'no_suitable_candidate')
            self.assertEqual(entry['decision_hash'],'decision1')
            write(Path(d)/'candidates/requests'/f'{key}.json',{'changed':True})
            with self.assertRaises(InputError):pending_manifest(d,result)


if __name__=='__main__':unittest.main()
