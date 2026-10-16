"""Evidence/temporal integrity, not scores for authored semantic labels."""
import copy
import json
from pathlib import Path
import unittest

from tracker.jev import DEFAULT_MODEL, validate_answers
from tracker.schema import InputError, digest
from tracker.semantic_map import validate, evidence, content_choice_request

ROOT = Path(__file__).resolve().parent.parent / 'research/semantic-map-review-2026-10-07'


def fixture(rid='00a05d9a7ebf17ee7760cc18'):
    return (json.loads((ROOT/'source-runs'/f'{rid}.json').read_text(encoding='utf-8')),
            json.loads((ROOT/'maps'/f'{rid}.json').read_text(encoding='utf-8')))


class SemanticMapTests(unittest.TestCase):
    def test_complete_records_preserve_authored_status_and_agent_coverage(self):
        for rid in ['00a05d9a7ebf17ee7760cc18','7046d56e989fdc4a4e7714d1']:
            run, doc = fixture(rid)
            self.assertEqual(validate(run, doc)['uncovered_agent_characters'], 0)
            self.assertIn('not measured', validate(run, doc)['semantic_accuracy'])
            self.assertEqual(doc['provenance']['origin'], 'assistant_authored_reference')

    def test_uncovered_text_and_overlapping_units_are_rejected(self):
        run, doc = fixture()
        broken=copy.deepcopy(doc);broken['units']=[u for u in broken['units'] if u['id']!='s6']
        with self.assertRaisesRegex(InputError,'Uncovered agent content'):validate(run,broken)
        broken=copy.deepcopy(doc);u=copy.deepcopy(broken['units'][0]);u['id']='duplicate';broken['units'].insert(1,u)
        with self.assertRaisesRegex(InputError,'Overlapping'):validate(run,broken)

    def test_paraphrase_keeps_exact_evidence_without_substring_requirement(self):
        run,doc=fixture();u=next(u for u in doc['units'] if u['id']=='s6')
        self.assertNotIn(u['content']['target']['text'], u['source']['text'])
        self.assertEqual(u['activity'],'orient')
        self.assertIn('Since the reproduction code',u['source']['text'])
        self.assertIn("Let's edit the code",u['source']['text'])
        self.assertGreater(validate(run,doc)['units'],0)
        u['content']['target']['evidence'][0]['text']='invented citation'
        with self.assertRaisesRegex(InputError,'Evidence does not match'):validate(run,doc)

    def test_local_field_cannot_use_later_feedback(self):
        run,doc=fixture();doc['units'][0]['content']['target']['evidence'].append(evidence(run,'e17'))
        with self.assertRaisesRegex(InputError,'Future evidence'):validate(run,doc)

    def test_feedback_link_requires_identity_and_plan_following_requires_plan(self):
        run,doc=fixture();r=next(r for r in doc['relations'] if r['type']=='feedback_for');r['to']='s1'
        with self.assertRaisesRegex(InputError,'Feedback link'):validate(run,doc)
        run,doc=fixture();r=next(r for r in doc['relations'] if r['type']=='realizes');r['type']='implements_step'
        with self.assertRaisesRegex(InputError,'actual Plan'):validate(run,doc)
        run,doc=fixture();event=next(e for e in run['events'] if e['id']=='e5');event['source_call_id']='another-call';doc['source_hash']=digest(run)
        with self.assertRaisesRegex(InputError,'call identity'):validate(run,doc)

    def test_revision_must_say_what_changed_and_target_binding_cannot_use_future(self):
        run,doc=fixture('7046d56e989fdc4a4e7714d1');r=next(r for r in doc['relations'] if r['type']=='revises');r.pop('changed_field')
        with self.assertRaisesRegex(InputError,'Revision must'):validate(run,doc)
        run,doc=fixture();doc['target_bindings'][0]['target_id']='fix'
        with self.assertRaisesRegex(InputError,'Future evidence'):validate(run,doc)

    def test_partial_support_is_not_whole_claim_verification(self):
        run,doc=fixture('7046d56e989fdc4a4e7714d1');r=next(r for r in doc['relations'] if r['type']=='supported_by')
        self.assertEqual(r['coverage'],'partial');r.pop('not_established')
        with self.assertRaisesRegex(InputError,'Partial support'):validate(run,doc)

    def test_readable_candidates_have_prefix_only_and_raw_argmax(self):
        run,doc=fixture();u=next(u for u in doc['units'] if u['id']=='s6')
        candidates=[u['content']['target'],{'text':'the issue','evidence':[u['source']]}]
        request=content_choice_request(run,u,'target',candidates,model=DEFAULT_MODEL)
        self.assertNotIn('e17',[p['event_id'] for p in request['state']['prefix']])
        self.assertNotIn('The output has changed',str(request['state']['prefix']))
        response={'answers':{'content':{'type':'choice','choice':'c1','confidence':0.99,
            'probabilities':{'c0':0.25,'c1':0.24,'not_expressed':0.18,'no_suitable_candidate':0.17,'unresolved':0.16}}}}
        self.assertEqual(validate_answers(response,request)['content']['value'],'c0')
        candidates[0]['evidence'].append(evidence(run,'e17'))
        with self.assertRaisesRegex(InputError,'Future evidence'):content_choice_request(run,u,'target',candidates,model=DEFAULT_MODEL)

    def test_content_builder_requires_anchored_established_unit(self):
        run,doc=fixture();u=doc['units'][0];c=[u['content']['target']]
        u['activity']='unresolved'
        with self.assertRaisesRegex(InputError,'Establish one activity'):content_choice_request(run,u,'target',c,model=DEFAULT_MODEL)
        u['activity']='orient';u['source']['text']='wrong'
        with self.assertRaisesRegex(InputError,'Unit source mismatch'):content_choice_request(run,u,'target',c,model=DEFAULT_MODEL)


if __name__=='__main__':unittest.main()
