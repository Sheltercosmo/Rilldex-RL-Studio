"""External annotation integrity; synthetic fixtures, not reference labels."""
import copy
import unittest

from research.inspect_reasoningflow import audit_document,audit_pair


def document():
    return {'doc_id':'synthetic','metadata':{'annotator':'Fixture A','is_human_annotated':True,'domain':'fixture'},
            'raw_text':{'question':'Solve.','response':'x=2. Check it. x*x=4. Later.'},
            'nodes':[{'id':nid,'source':source,'start':start,'end':end,'text':text,'label':label,'annotation':True}
                     for nid,source,start,end,text,label in [('q','question',0,6,'Solve.','context'),
                     ('a','response',0,5,'x=2. ','reasoning'),('p','response',5,15,'Check it. ','planning'),
                     ('b','response',15,22,'x*x=4. ','reasoning'),('later','response',22,28,'Later.','planning')]],
            'edges':[{'id':'e1','source_node_id':'a','dest_node_id':'p','label':'plan:verify'},
                     {'id':'e2','source_node_id':'p','dest_node_id':'b','label':'reason:execute'}]}


class ReasoningFlowAuditTests(unittest.TestCase):
    def test_native_agreement_does_not_create_product_labels_or_future_context(self):
        a=document();b=copy.deepcopy(a);b['metadata']['annotator']='Fixture B'
        summary,cases=audit_pair(a,b)
        self.assertEqual(summary['matched_eligible_nodes'],5)
        self.assertEqual(len(cases),2)
        self.assertTrue(all(c['native_consensus_eligible'] for c in cases))
        self.assertTrue(all(c['product_verify_reference'] is None for c in cases))
        planned=next(c for c in cases if c['edge_labels'][0]==['plan:verify'])
        self.assertEqual(planned['visible_prefix']['response'],'x=2. Check it. ')
        self.assertNotIn('x*x',planned['visible_prefix']['response'])

    def test_same_id_different_span_is_not_a_join(self):
        a=document();b=copy.deepcopy(a);b['metadata']['annotator']='Fixture B'
        b['nodes'][2].update(start=6,text='heck it. ')
        summary,cases=audit_pair(a,b)
        self.assertEqual(summary['matched_eligible_nodes'],4)
        self.assertEqual(cases,[])
        self.assertEqual(summary['unmatched_eligible_nodes'],[1,1])

    def test_different_ids_same_exact_span_and_source_can_be_paired(self):
        a=document();b=copy.deepcopy(a);b['metadata']['annotator']='Fixture B'
        for node in b['nodes']:node['id']='other-'+node['id']
        for edge in b['edges']:
            edge['source_node_id']='other-'+edge['source_node_id'];edge['dest_node_id']='other-'+edge['dest_node_id']
        summary,cases=audit_pair(a,b)
        self.assertEqual(summary['matched_eligible_nodes'],5)
        self.assertEqual(summary['eligible_native_focus_cases'],2)

    def test_source_corruption_and_duplicate_ids_are_excluded(self):
        a=document();a['nodes'][1]['text']='not from source'
        result=audit_document(a)
        self.assertNotIn('a',result['nodes'])
        self.assertTrue(any('span_mismatch' in i['reasons'] for i in result['issues']))
        a=document();a['nodes'].append(copy.deepcopy(a['nodes'][1]))
        result=audit_document(a);self.assertNotIn('a',result['nodes'])
        self.assertTrue(any('duplicate_node_id' in i['reasons'] for i in result['issues']))

    def test_self_link_and_future_source_are_not_evidence(self):
        a=document();a['edges'][0]['source_node_id']='p'
        a['edges'][1]['source_node_id']='later'
        result=audit_document(a)
        self.assertEqual(result['edges'],{})
        self.assertEqual(sum('not_forward_at_destination_cutoff' in i['reasons'] for i in result['issues']),2)

    def test_invalid_annotation_is_not_an_unannotated_negative(self):
        a=document();b=copy.deepcopy(a);b['metadata']['annotator']='Fixture B';b['edges'][0]['label']=''
        summary,cases=audit_pair(a,b)
        planned=next(c for c in cases if c['edge_labels'][0]==['plan:verify'])
        self.assertFalse(planned['native_consensus_eligible'])
        self.assertTrue(planned['excluded_edge_annotations'][1])
        self.assertEqual(summary['edge_endpoint_pairs_with_exclusions'],1)
        self.assertEqual(summary['edge_endpoint_pairs_with_disagreement'],0)

    def test_native_node_disagreement_remains_visible(self):
        a=document();b=copy.deepcopy(a);b['metadata']['annotator']='Fixture B';b['nodes'][2]['label']='reflection'
        summary,cases=audit_pair(a,b)
        self.assertEqual(summary['node_labels_agree'],4)
        self.assertTrue(all(c['edge_labels_agree'] for c in cases))
        self.assertTrue(all(not c['native_consensus_eligible'] for c in cases))

    def test_identity_or_nonhuman_annotations_cannot_be_paired(self):
        a=document();b=copy.deepcopy(a)
        with self.assertRaises(ValueError):audit_pair(a,b)
        b['metadata'].update(annotator='Fixture B',is_human_annotated=False)
        with self.assertRaises(ValueError):audit_pair(a,b)
        b['metadata']['is_human_annotated']=True;b['raw_text']['question']='Changed.'
        with self.assertRaises(ValueError):audit_pair(a,b)


if __name__=='__main__':unittest.main()
