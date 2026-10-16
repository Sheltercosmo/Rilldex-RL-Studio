"""Reviewed same-scope bindings reuse actions without changing their meanings."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from tracker import work_outline as wo, work_hierarchy as wh, graph_store
from tracker.schema import InputError, digest
import test_work_outline as outlines

PLAN='s2ac8166eb806c6e3d830'

def fixture():
    g=json.loads(Path('research/work-hierarchy-2026-10-13/software-evidence.json').read_text(encoding='utf-8'))
    g=g.get('graph',g)
    d=json.loads(Path('research/work-outline-2026-10-13/review.json').read_text(encoding='utf-8'))
    d['schema']=wo.BINDING_VERSION
    ref=next(s['evidence'] for s in wo.binding_scopes(g) if s['id']==PLAN)
    d['bindings']=[dict(item_id=item,scope_node_id=scope,evidence=deepcopy(ref),note='Authored test: same named work and target instance.')
        for item,scope in [('report-approach',PLAN),('draft',PLAN+':draft'),('convert',PLAN+':convert')]]
    return g,d

def by_name(g,cutoff=None):
    h=wh.build(g,cutoff)
    return {n['label']:n for n in h['work_outline']['items']},h

class OutlineBindingTests(unittest.TestCase):
    def test_steps_have_their_own_roles_and_ancestors_deduplicate(self):
        g,d=fixture();base=deepcopy(g);new=wo.fork(g,d);nodes,h=by_name(new)
        draft=nodes['Draft the report in Markdown']['execution_summary']
        convert=nodes['Convert the Markdown report to PDF']['execution_summary']
        self.assertEqual(draft['counts'],dict(actions=2,attempts=1,preparations=1,checks=0,with_feedback=2,with_assessment=0))
        self.assertEqual(convert['counts'],dict(actions=10,attempts=4,preparations=5,checks=1,with_feedback=10,with_assessment=9))
        self.assertEqual(draft['scope'],'direct');self.assertEqual(draft['binding_basis'],'reviewed_scopes')
        root=nodes['Build and evaluate an SVM drug-response predictor']['execution_summary']
        self.assertEqual(root['counts']['actions'],12);self.assertEqual(root['counts']['attempts'],5)
        self.assertEqual(len(root['binding_ids']),3)
        self.assertEqual(g,base)
        original_nodes=[n for n in new['nodes'] if not n['kind'].startswith('work_outline_')]
        self.assertEqual({n['id']:n for n in original_nodes},{n['id']:n for n in g['nodes']})
        self.assertTrue({e['id'] for e in g['edges']} <= {e['id'] for e in new['edges']})

    def test_empty_explicit_mapping_does_not_fall_back_to_containing_plan(self):
        g,d=fixture();d['bindings']=[];nodes,_=by_name(wo.fork(g,d))
        self.assertFalse(any('execution_summary' in n for n in nodes.values()))
        d.pop('bindings');d['schema']=wo.VERSION
        nodes,_=by_name(wo.fork(g,d))
        self.assertEqual(nodes['Draft in Markdown, then convert to PDF']['execution_summary']['binding_basis'],'containing_plan_citation')

    def test_binding_time_withheld_until_evidence_exists(self):
        g,d=fixture();events=wo.source_index(g);later=events['e98']['properties']['text']
        d['bindings'][2]['evidence']=dict(event_id='e98',start=0,end=len(later),text=later)
        new=wo.fork(g,d);early,_=by_name(new,'e97');late,_=by_name(new,'e98')
        self.assertNotIn('execution_summary',early['Convert the Markdown report to PDF'])
        self.assertEqual(late['Convert the Markdown report to PDF']['execution_summary']['counts']['attempts'],4)
        self.assertEqual(early['Draft the report in Markdown']['execution_summary']['counts']['attempts'],1)
        first,_=by_name(new,'e65');self.assertEqual(first['Draft the report in Markdown']['execution_summary']['counts']['actions'],0)

    def test_duplicate_whole_and_step_membership_counts_action_once_and_keeps_both_bindings(self):
        g,d=fixture();extra=deepcopy(d['bindings'][1]);extra['item_id']='report-approach';d['bindings'].append(extra)
        nodes,_=by_name(wo.fork(g,d));r=nodes['Draft in Markdown, then convert to PDF']['execution_summary']
        self.assertEqual(r['counts']['actions'],12)
        own=[m for m in r['rows'][0]['memberships'] if m['work_id'].endswith(':report-approach')]
        self.assertEqual(len(own),1);self.assertEqual(len(own[0]['binding_ids']),2)

    def test_reject_missing_targets_wrong_kind_quotes_context_time_and_unattributed_review(self):
        g,d=fixture()
        for mutation in ['target','item','kind','hypothesis','quote','context','time','author','duplicate','rationale']:
            value=deepcopy(d);source=deepcopy(g);b=value['bindings'][0]
            if mutation=='target':b['scope_node_id']='absent'
            if mutation=='item':b['item_id']='absent'
            if mutation=='kind':b['scope_node_id']='event:e65'
            if mutation=='hypothesis':next(i for i in value['items'] if i['id']==b['item_id'])['kind']='hypothesis'
            if mutation=='quote':b['evidence']['text']='wrong quote'
            if mutation=='context':next(n for n in source['nodes'] if n['id']=='event:e1')['properties']['context_id']='different'
            if mutation=='time':b['evidence']=deepcopy(value['items'][0]['evidence'])
            if mutation=='author':next(n for n in source['nodes'] if n['id']=='event:e65')['properties']['actor']='user'
            if mutation=='duplicate':value['bindings'].append(deepcopy(b))
            if mutation=='rationale':b['note']=' '
            with self.subTest(mutation=mutation),self.assertRaises(InputError):wo.validate(source,value)

    def test_binding_edge_and_document_must_agree(self):
        g,d=fixture();new=wo.fork(g,d)
        next(e for e in new['edges'] if e['type']=='outline_same_scope')['target']=PLAN+':convert'
        with self.assertRaises(InputError):wo.project(new,100)

    def test_source_pointer_metadata_is_not_part_of_editable_quote_contract(self):
        g,_=fixture();template=wo.template(g)
        self.assertEqual(template['binding_schema'],wo.BINDING_VERSION)
        self.assertEqual(len(template['binding_scopes']),5)
        for scope in template['binding_scopes']:
            self.assertEqual(set(scope['evidence']),{'event_id','start','end','text'})
            wo.anchor(scope['evidence'],wo.source_index(g))

    def test_existing_model_candidate_documents_and_review_identity_stay_compatible(self):
        _,g,d,_=outlines.fixture();new=wo.fork(g,d)
        self.assertEqual(wo.template(new)['document']['schema'],wo.VERSION)
        self.assertNotIn('bindings',wo.template(new)['document'])
        wo.checked(new)
        source,doc=fixture();one=wo.fork(source,doc);two=wo.fork(one,wo.template(one)['document'])
        self.assertEqual(one['observer'],two['observer'])
        self.assertEqual([n['id'] for n in one['nodes'] if n['kind']=='work_outline_item'],[n['id'] for n in two['nodes'] if n['kind']=='work_outline_item'])
        wo.checked(two)


if __name__=='__main__':unittest.main()
