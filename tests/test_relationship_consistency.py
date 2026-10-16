"""One source relationship must not become contradictory evidence across views."""
from copy import deepcopy
import unittest

from test_feedback_opportunities import control,graph
from test_work_hierarchy import finish
from tracker import map_relationships,feedback_opportunities,feedback_timing,feedback_followthrough,graph_queries


def captured():
    run,ex,result=control(choice='f0')
    return graph(run,ex,result)


class RelationshipConsistencyTests(unittest.TestCase):
    def test_new_unit_prompt_uses_only_visible_same_context_evidence(self):
        from tracker.semantic_extraction import generation_request
        from tracker.semantic_workspace import DEFAULT_CONTEXT
        run,ex,_=control()
        for e in run['events']:e['context_id']='local'
        other=run['events'][0];other['context_id']='foreign'
        copied=run['events'][1];copied['copied_context']=True
        current=ex['units'][-1]['source'];req=generation_request(run,current,'report',DEFAULT_CONTEXT)
        ids={e['id'] for e in req['prefix']}
        self.assertNotIn(other['id'],ids);self.assertNotIn(copied['id'],ids)
        self.assertNotIn(other['id'],req['omitted_context_event_ids'])
        self.assertIn(current['event_id'],ids)
        run['events'][-1]['order_known']=False
        req=generation_request(run,current,'report',DEFAULT_CONTEXT)
        self.assertEqual([e['id'] for e in req['prefix']],[current['event_id']])

    def test_existing_workspaces_and_feedback_profiles_remain_pinned(self):
        import tempfile
        from pathlib import Path
        from tracker import semantic_workspace as workspace,semantic_layers,feedback_retrieval
        run,_,_=control()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'workspace';old={**workspace.DEFAULT_CONTEXT,'schema':'readable-context/2'}
            config=workspace.initialize(root,run,context_policy=old,feedback_profile='feedback-references/1')
            self.assertEqual(workspace.initialize(root,run,feedback_profile='feedback-references/1'),config)
            self.assertEqual(workspace.initialize(Path(tmp)/'new',run)['context_policy']['schema'],'readable-context/3')
        self.assertEqual(semantic_layers.feedback_protocol('feedback-references/1')['retrieval_version'],feedback_retrieval.HYBRID_VERSION)
        self.assertEqual(semantic_layers.feedback_protocol('feedback-references/2')['retrieval_version'],feedback_retrieval.CONTEXT_VERSION)

    def test_another_context_does_not_supply_a_feedback_reference_or_query_match(self):
        g=captured()
        for n in g['nodes']:
            if n['kind']=='event' and n['properties']['kind'] in {'message','reasoning'} and n['properties']['actor']=='agent':
                n['properties']['context_id']='another-session'
        g=finish(g)
        self.assertEqual(map_relationships.inspect(g)['incompatible'],3)
        measure=feedback_opportunities.project(g)
        self.assertEqual(measure['metrics']['opportunities'],1)
        self.assertIsNone(measure['metrics']['value'])
        self.assertEqual(measure['observations'][0]['window_event_ids'],[])
        self.assertEqual(graph_queries.evaluate(g,graph_queries.PRESETS['assessment_of_inspection_feedback'])['matched_anchors'],0)
        self.assertEqual(feedback_followthrough.project(g)['counts']['reference_pairs'],0)

    def test_unresolved_order_cannot_create_a_positive_measure_or_path(self):
        g=captured()
        for n in g['nodes']:
            if n['kind']=='event' and n['properties']['actor']=='agent':n['properties']['order_known']=False
        g=finish(g)
        self.assertGreater(map_relationships.inspect(g)['incompatible'],0)
        self.assertIsNone(feedback_opportunities.project(g)['metrics']['value'])
        self.assertEqual(graph_queries.evaluate(g,graph_queries.PRESETS['assessment_of_inspection_feedback'])['matched_anchors'],0)
        self.assertIsNone(feedback_timing.project(g)['metrics']['value'])
        self.assertEqual(feedback_followthrough.project(g)['counts']['reference_pairs'],0)

    def test_evidence_use_of_tool_feedback_has_its_recipients_actor(self):
        g=captured()
        for e in g['edges']:
            if e['type']=='assesses':e['type']='uses_evidence'
        self.assertEqual(map_relationships.inspect(finish(g))['incompatible'],0)

    def test_corrupt_or_foreign_citations_are_not_valid_relation_evidence(self):
        for mode in ['quote','context','future']:
            with self.subTest(mode=mode):
                g=captured();e=next(e for e in g['edges'] if e['type']=='assesses')
                if mode=='quote':e['properties']['context_evidence'][0]['text']='invented'
                else:
                    event=next(n['properties'] for n in g['nodes'] if n['kind']=='event' and n['properties']['actor']=='user')
                    e['properties']['context_evidence'].append(dict(event_id=event['id'],start=0,end=len(event['text']),text=event['text'],source_pointer=event.get('source_pointer')))
                    if mode=='context':event['context_id']='hidden-context'
                    else:event['index']=999;next(n for n in g['nodes'] if n['kind']=='event' and n['properties']['id']==event['id'])['event_index']=999
                audit=map_relationships.inspect(finish(g))
                self.assertIn(e['id'],{r['edge_id'] for r in audit['relationships'] if r['status']=='incompatible'})
                matches=graph_queries.evaluate(finish(g),graph_queries.PRESETS['assessment_of_inspection_feedback'])['cases'][0]['matches']
                self.assertNotIn(e['id'],{m['edge_id'] for m in matches})

    def test_work_path_rejects_reference_with_unresolved_source_order(self):
        from test_work_route_context import example
        from tracker import work_navigation
        _,g,_=example()
        unit=next(n for n in g['nodes'] if n['id']=='unit-3')
        source=next(n for n in g['nodes'] if n['kind']=='event' and n['properties']['id']==unit['properties']['source']['event_id'])
        source['properties']['order_known']=False
        result=work_navigation.project(finish(g))
        self.assertFalse(any(e.get('relation_type')=='revises' for e in result['links']))
        self.assertTrue(any(e['reason']=='unresolved_source_order' for e in result['context']['issues']))

    def test_valid_references_keep_their_witnesses_without_mutating_the_graph(self):
        g=captured();before=deepcopy(g)
        self.assertEqual(map_relationships.inspect(g)['incompatible'],0)
        self.assertEqual(feedback_opportunities.project(g)['metrics']['value'],1)
        self.assertEqual(graph_queries.evaluate(g,graph_queries.PRESETS['assessment_of_inspection_feedback'])['matched_anchors'],1)
        self.assertEqual(g,before)


if __name__=='__main__':unittest.main()
