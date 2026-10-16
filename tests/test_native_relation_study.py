import copy
import json
from pathlib import Path
import tempfile
import unittest

from test_reasoningflow_audit import document
from research.inspect_reasoningflow import audit_document
from research.reasoningflow_relations import source_units,make_request,reference,self_contained_request,compare_binding,RELATIONS
from tracker.jev import DEFAULT_MODEL,SELECTION_POLICY,validate_answers
from tracker.relation_candidates import retrieve
from tracker.schema import InputError,digest


class NativeRelationStudyTests(unittest.TestCase):
    def test_native_labels_and_future_text_are_absent_from_request(self):
        doc=document();units=source_units(doc);subject=units[2]
        candidates=retrieve(units,subject);request=make_request(doc,units,subject,candidates,'plan:verify')
        self.assertEqual(request['state']['raw_prefix']['response'],'x=2. Check it. ')
        self.assertFalse(any('label' in u or 'annotation' in u for u in request['state']['source_units']))
        changed=copy.deepcopy(doc)
        for node in changed['nodes']:node['label']='unavailable gold category'
        changed['edges']=[];changed['metadata']['annotator']='unavailable'
        self.assertEqual(request,make_request(changed,source_units(changed),subject,candidates,'plan:verify'))

    def test_multiple_candidates_get_independent_choices_and_list_escape(self):
        doc=document();units=source_units(doc);subject=units[3]
        request=make_request(doc,units,subject,retrieve(units,subject),'reason:execute')
        self.assertEqual(len(request['questions']),4)
        for key,value in request['questions'].items():
            if key!='candidate_set':self.assertEqual(set(value['criteria']),{'present','absent','unresolved'})
        self.assertIn('no_suitable_candidate',request['questions']['candidate_set']['criteria'])

    def test_future_or_altered_candidate_cannot_be_inserted(self):
        doc=document();units=source_units(doc);subject=units[2];candidate=retrieve(units,subject)
        candidate['candidates'][0]['unit']=units[-1]
        with self.assertRaises(InputError):make_request(doc,units,subject,candidate,'plan:verify')

    def test_explicit_binding_preserves_source_candidates_and_original(self):
        doc=document();units=source_units(doc);subject=units[2];candidate=retrieve(units,subject)
        for relation in RELATIONS:
            original=make_request(doc,units,subject,candidate,relation);before=copy.deepcopy(original)
            case={'requests':{'hybrid':original},'relation':relation,'subject':subject,'candidate_audit':candidate}
            changed=self_contained_request(case)
            self.assertEqual(original,before)
            self.assertEqual(changed['model'],original['model'])
            self.assertEqual(changed['questions']['candidate_set'],original['questions']['candidate_set'])
            state=copy.deepcopy(changed['state']);state['harness']=original['state']['harness']
            self.assertEqual(state,original['state'])
            self.assertEqual(set(changed['questions']),set(original['questions']))
            for i,c in enumerate(candidate['candidates']):
                q=changed['questions'][f'link_{i}']
                self.assertIn(RELATIONS[relation],q['instructions'])
                self.assertIn(c['unit']['text'],q['instructions'])
                self.assertIn(subject['text'],q['instructions'])
                self.assertEqual(set(q['criteria']),set(original['questions'][f'link_{i}']['criteria']))

    def test_native_nonedge_disagreement_and_invalid_annotation_stay_distinct(self):
        a=document();b=copy.deepcopy(a);b['metadata']['annotator']='B';units=source_units(a)
        audits=[audit_document(a),audit_document(b)]
        self.assertEqual(reference(audits,units[1],units[2],'plan:verify')[0],'present')
        self.assertEqual(reference(audits,units[0],units[2],'plan:verify')[0],'absent')
        b['edges'][0]['label']='plan:proceed'
        self.assertEqual(reference([audit_document(a),audit_document(b)],units[1],units[2],'plan:verify'),(None,'edge_annotation_disagreement'))
        b['edges'][0]['label']=''
        self.assertEqual(reference([audit_document(a),audit_document(b)],units[1],units[2],'plan:verify'),(None,'invalid_edge_annotation'))

    def test_paired_summary_separates_unknown_references_and_reused_cost(self):
        doc=document();units=source_units(doc);subject=units[3];candidate=retrieve(units,subject)
        original=make_request(doc,units,subject,candidate,'reason:execute')
        case={'case_id':'fixture','set':'development','domain':'math','doc_id':'fixture',
              'relation':'reason:execute','subject':subject,'candidate_audit':candidate,'requests':{'hybrid':original},
              'native_references':{k:{'value':v,'basis':'test_fixture'} for k,v in {
                  'link_0':'absent','link_1':'present','link_2':None,'candidate_set':'linked_candidate_present'}.items()}}
        changed=self_contained_request(case)
        case['requests']={'baseline':original,'repeat':copy.deepcopy(original),'self_contained':changed}
        variants=list(case['requests'])
        manifest={'version':'native-relations-binding-probe/1','variants':variants,'model':DEFAULT_MODEL,
                  'selection_policy':SELECTION_POLICY,'cases_hash':digest([case])}
        choices={'baseline':['present','absent','absent','linked_candidate_present'],
                 'repeat':['absent','absent','present','not_applicable'],
                 'self_contained':['absent','present','unresolved','linked_candidate_present']}
        with tempfile.TemporaryDirectory() as root:
            root=Path(root)
            (root/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
            (root/'cases.json').write_text(json.dumps([case]),encoding='utf-8')
            for variant in variants:
                request=case['requests'][variant];raw={}
                for (key,q),value in zip(request['questions'].items(),choices[variant]):
                    raw[key]={'type':'choice','probabilities':{option:float(option==value) for option in q['criteria']}}
                record={'case_id':'fixture','set':'development','variant':variant,'model':DEFAULT_MODEL,
                        'selection_policy':SELECTION_POLICY,'request_hash':digest(request),
                        'answers':validate_answers({'answers':raw},request),'usage':{'input_tokens':11}}
                if variant=='baseline':record['reuse_basis']='Test reused result'
                (root/(variant+'-development.jsonl')).write_text(json.dumps(record)+'\n',encoding='utf-8')
            result=compare_binding(root)
            self.assertTrue(result['complete']);self.assertEqual(result['new_provider_calls'],2)
            self.assertEqual(result['reused_results'],1);self.assertEqual(result['new_usage']['input_tokens'],22)
            stats=result['variants']['self_contained']['counts']['reason:execute|pair_membership|all']
            self.assertEqual((stats['reference_scored'],stats['reference_unresolved'],stats['true_positive']),(2,1,1))
            transitions=result['pairs']['baseline__self_contained']['counts']['reason:execute|pair_membership|all']
            self.assertEqual((transitions['compared'],transitions['changed'],transitions['became_matching']),(3,3,2))
            self.assertEqual(len(result['variants']['repeat']['cross_question_disagreements']),1)
            (root/'repeat-development.jsonl').unlink()
            self.assertFalse(compare_binding(root)['complete'])


if __name__=='__main__':unittest.main()
