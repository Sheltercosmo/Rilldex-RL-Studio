"""Graph query contracts on contrasts where proximity gives the wrong answer."""
import copy
import unittest
from unittest.mock import patch
from tracker import graph_queries as gq
from tracker.schema import InputError


def node(identity, position, activity=None, actor='agent', trajectory='main', kind='unit'):
    return {'id':identity,'kind':kind,'activity':activity,'trajectory_id':trajectory,
            'event_index':position,'properties':{'actor':actor,'kind':'feedback' if actor=='environment' else 'action' if activity in {'inspect','construct'} else 'semantic','source':{'start':0,'end':10}}}


def edge(source, target, kind):
    return {'id':source+':'+kind+':'+target,'source':source,'target':target,'type':kind,'properties':{}}


class EvidencePathTests(unittest.TestCase):
    def graph(self):
        return {'id':'fixture','run_id':'fixture','observer':'fixture','metadata':{},'nodes':[
            node('old',0,'plan'),node('inspect',1,'inspect'),node('response',2,actor='environment'),
            node('other-operation',3,'construct'),node('other-response',4,actor='environment'),
            node('assess-other',5,'orient'),node('assess-inspection',6,'orient'),node('revise',7,'construct')],
            'edges':[edge('response','inspect','feedback_for'),edge('other-response','other-operation','feedback_for'),
                edge('assess-other','other-response','assesses'),edge('assess-inspection','response','assesses'),
                edge('revise','old','revises'),edge('revise','response','uses_evidence')]}

    def test_connected_feedback_excludes_unrelated_nearby_assessment(self):
        graph=self.graph()
        nearby=gq.evaluate(graph,gq.PRESETS['assessment_after_inspect'])
        connected=gq.evaluate(graph,gq.PRESETS['assessment_of_inspection_feedback'])
        self.assertEqual(len(nearby['cases'][0]['matches']),2)
        matches=connected['cases'][0]['matches']
        self.assertEqual([m['source'] for m in matches],['assess-inspection'])
        self.assertEqual(matches[0]['evidence_path']['node_ids'],['response','inspect'])
        self.assertEqual(connected['association'],'stored_evidence_path')
        graph['edges']=[e for e in graph['edges'] if e['source']!='assess-inspection']
        self.assertEqual(gq.evaluate(graph,gq.PRESETS['assessment_after_inspect'])['matched_anchors'],1)
        self.assertEqual(gq.evaluate(graph,gq.PRESETS['assessment_of_inspection_feedback'])['matched_anchors'],0)

    def revision(self):
        return {**gq.PRESETS['assessment_of_inspection_feedback'],'relation':'revises',
            'evidence_path':{'start':'relation_source','hops':[
                {'direction':'outgoing','relations':['uses_evidence']},
                {'direction':'outgoing','relations':['feedback_for']}]}}

    def test_revision_can_follow_used_feedback_to_the_exact_inspection(self):
        result=gq.evaluate(self.graph(),self.revision())
        match=result['cases'][0]['matches'][0]
        self.assertEqual(match['evidence_path']['node_ids'],['revise','response','inspect'])
        self.assertEqual(match['target'],'old')
        self.assertEqual(len(match['evidence_links']),2)
        self.assertIsNone(result['behavior_rate'])

    def test_incoming_traversal_preserves_original_edge_direction(self):
        graph=self.graph()
        # Native recipient identity remains necessary even when this query
        # follows a different, incoming edge to establish its path.
        graph['edges'].append(edge('inspect','response','has_response'))
        query=copy.deepcopy(gq.PRESETS['assessment_of_inspection_feedback'])
        query['evidence_path']['hops']=[{'direction':'incoming','relations':['has_response']}]
        witness=gq.evaluate(graph,query)['cases'][0]['matches'][0]['evidence_path']
        self.assertEqual(witness['traversals'][0],{'edge_id':'inspect:has_response:response',
            'from':'response','to':'inspect','direction':'incoming'})

    def test_future_cross_trajectory_and_unresolved_intermediates_cannot_match(self):
        for field,value in [('event_index',10),('trajectory_id','different'),('kind','unresolved_reference')]:
            graph=self.graph();next(n for n in graph['nodes'] if n['id']=='response')[field]=value
            self.assertEqual(gq.evaluate(graph,self.revision())['matched_anchors'],0)

    def test_window_is_agent_units_and_each_anchor_counts_once(self):
        graph=self.graph();query=copy.deepcopy(gq.PRESETS['assessment_of_inspection_feedback'])
        query['within_units']=2
        self.assertEqual(gq.evaluate(graph,query)['matched_anchors'],0)
        query['within_units']=3
        self.assertEqual(gq.evaluate(graph,query)['matched_anchors'],1)
        graph['edges'].append(edge('revise','response','assesses'));query['within_units']=8
        result=gq.evaluate(graph,query)
        self.assertEqual((result['anchors'],result['matched_anchors']), (1,1))
        self.assertEqual(len(result['cases'][0]['matches']),2)

    def test_search_budget_failure_does_not_publish_a_partial_rate(self):
        with patch.object(gq,'MAX_PATH_EDGE_VISITS',0):
            with self.assertRaisesRegex(InputError,'No partial rate'):
                gq.evaluate(self.graph(),self.revision())

    def test_same_event_unknown_offsets_and_later_declared_cutoffs_are_excluded(self):
        graph=self.graph();response=next(n for n in graph['nodes'] if n['id']=='response')
        response['event_index']=7;response['properties'].pop('source')
        self.assertEqual(gq.evaluate(graph,self.revision())['matched_anchors'],0)
        # A raw event includes its whole text, not a fabricated zero-length span.
        response['kind']='event';response['properties']['text']='x'*20
        self.assertEqual(gq.evaluate(graph,self.revision())['matched_anchors'],0)
        graph=self.graph();future=node('event:future',9,kind='event');future['properties']={'id':'future','text':'later evidence'}
        graph['nodes'].append(future)
        next(e for e in graph['edges'] if e['type']=='uses_evidence')['properties']['cutoff']={'event_id':'future','end':5}
        self.assertEqual(gq.evaluate(graph,self.revision())['matched_anchors'],0)

    def test_path_contract_rejects_malformed_or_unbounded_instructions(self):
        query=self.revision()
        invalid=[{**query,'schema':[]},{**query,'evidence_path':{'start':[],'hops':[]}},
            {**query,'evidence_path':{'start':'relation_source','hops':[{'direction':[],'relations':['x']}]}},
            {**query,'require_evidence_link':True},{**query,'evidence_path':{'start':'sql','hops':[]}},
            {**query,'evidence_path':{'start':'relation_source','hops':query['evidence_path']['hops']*2}},
            {**query,'evidence_path':{'start':'relation_source','hops':[{'direction':'outgoing','relations':['uses_evidence','uses_evidence']}]}},
            {**query,'evidence_path':{'start':'relation_source','hops':[{'direction':'any','relations':['x']}]}},
            {**query,'evidence_path':{'start':'relation_source','hops':[{'direction':'outgoing','relations':['x'],'sql':'select'}]}}]
        for value in invalid:
            with self.assertRaises(InputError):gq.validate(value)
        temporal=gq.validate({**query,'evidence_path':None})
        self.assertEqual(gq.evaluate(self.graph(),temporal)['association'],'temporal_only')

    def test_legacy_requirement_keeps_its_version_and_direct_link_meaning(self):
        query={**gq.PRESETS['revision_after_inspect'],'require_evidence_link':True}
        self.assertEqual(gq.validate(query)['schema'],gq.VERSION)
        graph=self.graph()
        self.assertEqual(gq.evaluate(graph,query)['matched_anchors'],0)
        graph['edges'].append(edge('revise','inspect','responds_to'))
        self.assertEqual(gq.evaluate(graph,query)['matched_anchors'],1)


if __name__=='__main__':unittest.main()
