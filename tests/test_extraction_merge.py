from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from tracker.extraction_merge import merge
from tracker.schema import InputError,digest
from tracker.semantic_extraction import Pipeline,windows,audit_result,read,write,load_extraction
from tests.test_participant_extraction import CandidateFixture
from tests.test_semantic_extraction import fixture,response


class ExtractionMergeTests(unittest.TestCase):
    def setup_parts(self,root):
        run=fixture();eligible=windows(run,include_user=True)
        agent_ids=[w['id'] for w in eligible if w['kind']!='user_span']
        user_ids=[w['id'] for w in eligible if w['kind']=='user_span']
        inputs=[]
        for label,ids in [('agent',agent_ids),('user',user_ids)]:
            directory=root/label;engine=Pipeline(directory,CandidateFixture(directory/'c'),response)
            inputs.append((engine.run(run,window_ids=ids,include_user=True),directory))
        return run,inputs

    def test_disjoint_merge_preserves_selections_source_order_and_replay(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);run,inputs=self.setup_parts(root);original=deepcopy(inputs)
            result,audit=merge(run,inputs,root/'merged')
            self.assertEqual(inputs,original);self.assertTrue(result['whole_run'])
            self.assertEqual([w['id'] for w in result['windows']],[w['id'] for w in windows(run,include_user=True)])
            for part,_ in inputs:
                for unit in part['units']:self.assertIn(unit,result['units'])
            self.assertEqual(audit['contributions_by_actor'],{'agent':1,'user':2})
            self.assertEqual(result['source_exclusions'],[])
            self.assertTrue(load_extraction(run,root/'merged')['available'])

    def test_overlap_is_not_silently_deduplicated(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);run,inputs=self.setup_parts(root)
            with self.assertRaisesRegex(InputError,'overlap'):merge(run,[inputs[0],inputs[0]],root/'merged')
            self.assertFalse((root/'merged/results').exists())

    def test_missing_windows_require_explicit_scope_and_cannot_claim_whole_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);run,inputs=self.setup_parts(root)
            with self.assertRaisesRegex(InputError,'omitted'):merge(run,[inputs[0]],root/'merged')
            excluded=[{'window_id':w['id'],'source':w,'reason':'Selected-source test scope','basis':'test fixture'}
                      for w in windows(run,include_user=True) if w['kind']=='user_span']
            result,audit=merge(run,[inputs[0]],root/'merged',excluded)
            self.assertFalse(result['whole_run'])
            self.assertEqual(load_extraction(run,root/'merged')['document']['source_exclusions'],excluded)
            tampered=deepcopy(result);tampered['source_exclusions'].pop()
            with self.assertRaisesRegex(InputError,'exclusions'):audit_result(run,tampered,root/'merged')
            tampered=deepcopy(result);tampered['whole_run']=True
            with self.assertRaisesRegex(InputError,'exclusions'):audit_result(run,tampered,root/'merged')

    def test_conflicting_decision_file_does_not_replace_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);run,inputs=self.setup_parts(root)
            result,_=merge(run,inputs,root/'merged')
            key=result['units'][0]['activity_request'];target=root/'merged/decisions'/f'{key}.json'
            original=target.read_text();target.write_text('{}')
            with self.assertRaisesRegex(InputError,'Conflicting'):merge(run,inputs,root/'merged')
            self.assertEqual(target.read_text(),'{}')

    def test_review_cannot_claim_a_nonexistent_selected_relation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);run,inputs=self.setup_parts(root)
            result,_=merge(run,inputs,root/'merged');unit=result['units'][0]
            review={'schema':'semantic-source-review/1','source_hash':digest(run),
                    'extraction_hash':digest(result),'annotator':'test',
                    'notes':[{'kind':'relation_review','text':'Specific relationship needs review.',
                              'unit_ids':[unit['id']],'evidence':[unit['source']],
                              'relation_ref':{'from':unit['id'],'to':unit['id'],'type':'invented'}}]}
            write(root/'merged/reviews'/run['id']/f'{digest(result)}.json',review)
            with self.assertRaisesRegex(InputError,'relation reference'):load_extraction(run,root/'merged')


if __name__=='__main__':unittest.main()
