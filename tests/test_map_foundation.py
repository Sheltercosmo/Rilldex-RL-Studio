"""Source-bound map invariants, not independent semantic accuracy labels."""
import unittest
from tracker.work_hierarchy import build
from test_work_hierarchy import graph, finish


class MapFoundationTests(unittest.TestCase):
    def test_assessment_from_another_context_is_not_a_visible_relationship(self):
        g=graph()
        next(n for n in g['nodes'] if n['id']=='event:e3')['properties']['context_id']='other'
        out=build(finish(g))
        self.assertFalse(any(e['type']=='assesses' for e in out['links']))
        self.assertNotIn('review',{n['id'] for n in out['nodes']})

    def test_assessment_before_its_feedback_is_not_a_visible_relationship(self):
        g=graph()
        for n in g['nodes']:
            if n['id'] in {'review','event:e3'}:n['event_index']=1
        out=build(finish(g))
        self.assertFalse(any(e['type']=='assesses' for e in out['links']))

    def test_assessment_by_another_actor_is_not_attributed_to_the_plan_actor(self):
        g=graph();next(n for n in g['nodes'] if n['id']=='review')['properties']['actor']='other'
        self.assertFalse(any(e['type']=='assesses' for e in build(finish(g))['links']))

    def test_unresolved_source_order_cannot_support_an_assessment_sequence(self):
        g=graph();next(n for n in g['nodes'] if n['id']=='event:e3')['properties']['order_known']=False
        self.assertFalse(any(e['type']=='assesses' for e in build(finish(g))['links']))

    def test_copied_or_external_context_is_not_agent_observed_feedback(self):
        for field,value in [('copied_context',True),('kind','external_feedback'),('agent_visibility','not_established')]:
            with self.subTest(field=field):
                g=graph();next(n for n in g['nodes'] if n['id']=='event:e2')['properties'][field]=value
                self.assertFalse(any(e['type']=='assesses' for e in build(finish(g))['links']))

    def test_changed_unit_invalidates_relations_that_reference_it_indirectly(self):
        from test_unit_reviews import UnitReviewTests, document
        from tracker import unit_reviews
        fixture=UnitReviewTests();run,g,units=fixture.fixture()
        # Endpoints survive, but this classification explicitly depended on the
        # unit being corrected. It must not survive solely on endpoint identity.
        uid=next(n['id'] for n in g['nodes'] if n['kind']=='unit' and n['properties'].get('kind')=='action')
        candidates=[n['id'] for n in g['nodes'] if n['kind']=='unit' and n['id']!=uid]
        # Check-correspondence response edges use action_unit_id while their
        # endpoints are the returned feedback and the earlier request.
        e=unit_reviews.edge(candidates[0],candidates[-1],'contains_requested_material',
                            {'basis':'authored dependency control','action_unit_id':uid})
        dependent=unit_reviews.edge(candidates[-1],candidates[0],'derived_control',{'evidence_ids':[e['id']]})
        independent=unit_reviews.edge(candidates[-1],candidates[0],'independent_control',{'explanation':uid})
        g['edges'].extend([e,dependent,independent])
        g['semantic_context']['requested_check_observations']={'observations':[{'action_unit_id':uid}]}
        g=unit_reviews.finish(g)
        revised=unit_reviews.fork(run,g,document(run,g,uid,'verify'))
        self.assertNotIn(e['id'],{e['id'] for e in revised['edges']})
        self.assertNotIn(dependent['id'],{e['id'] for e in revised['edges']})
        self.assertIn(independent['id'],{e['id'] for e in revised['edges']})
        self.assertNotIn('requested_check_observations',revised['semantic_context'])

    def test_valid_assessment_and_same_event_earlier_reference_are_retained(self):
        from tracker.map_relationships import inspect
        g=graph();a=inspect(g)
        self.assertEqual((a['checked'],a['incompatible']),(1,0))
        self.assertTrue(any(e['type']=='assesses' for e in build(g)['links']))
        for n in g['nodes']:
            if n['id']=='review':
                n['event_index']=0;n['properties']['source'].update(event_id='e0',start=9,end=18)
        next(e for e in g['edges'] if e['id']=='review').update(type='uses_evidence',target='plan')
        self.assertEqual(inspect(finish(g))['incompatible'],0)

    def test_relationship_audit_is_independent_of_input_order_and_does_not_mutate(self):
        from copy import deepcopy
        from tracker.map_relationships import inspect
        g=graph();before=deepcopy(g);a=inspect(g)
        self.assertEqual(g,before)
        g['nodes'].reverse();g['edges'].reverse()
        self.assertEqual(inspect(g),a)

    def test_source_audit_and_sdk_do_not_claim_semantic_accuracy(self):
        from test_unit_reviews import UnitReviewTests
        from tracker.map_foundation import inspect
        from tracker.schema import InputError
        from rilldex import Workspace
        fixture=UnitReviewTests();run,g,_=fixture.fixture();store=fixture.store(run,g)
        self.addCleanup(fixture.doCleanups)
        report=inspect(g,run)
        self.assertEqual(report['source_checks']['status'],'passed')
        self.assertEqual(report['semantic_review']['status'],'not_independently_validated')
        self.assertEqual(Workspace(store.path).map_foundation(g['id'])['relationships'],report['relationships'])
        with self.assertRaises(InputError):Workspace(store.path,experiment='missing').map_foundation(g['id'])
        with self.assertRaises(InputError):Workspace(store.path).map_foundation(g['id'],limit=1)
        n=next(n for n in g['nodes'] if n['kind']=='unit');n['properties']['source']['text']='altered quote'
        with self.assertRaisesRegex(InputError,'source-bound'):inspect(finish(g),run)

    def test_future_incompatible_relationship_does_not_change_an_earlier_view(self):
        g=graph();early=build(g,'e0')
        next(n for n in g['nodes'] if n['id']=='event:e3')['properties']['context_id']='other'
        later=build(finish(g),'e0')
        for field in ['nodes','links','counts','issues']:
            self.assertEqual(early[field],later[field])

    def test_high_level_plan_does_not_import_meaning_from_future_source(self):
        from tracker.map_foundation import content_sources
        g=graph();plan=next(n for n in g['nodes'] if n['id']=='plan')
        plan['properties']['content']['summary']={'text':'Later explanation',
            'evidence':[dict(event_id='e3',start=0,end=8,text='source 3')]}
        g=finish(g);audit=content_sources(g)
        self.assertEqual(audit['excluded_unit_ids'],['plan'])
        self.assertEqual(audit['issues'][0]['reason'],'future_content_source')
        for cutoff in (None,'e0'):
            out=build(g,cutoff);self.assertEqual(out['counts']['plans'],0)
            self.assertNotIn('plan',{n['id'] for n in out['nodes']})

    def test_content_citations_are_exact_local_and_visible_not_just_matching_words(self):
        from tracker.map_foundation import content_sources
        from copy import deepcopy
        g=graph();plan=next(n for n in g['nodes'] if n['id']=='plan')
        event=next(n for n in g['nodes'] if n['id']=='event:e0')['properties']
        plan['properties']['content']['summary']={'text':'Plan', 'evidence':[dict(plan['properties']['source'])]}
        self.assertEqual(content_sources(g)['excluded_unit_ids'],[])
        for change,reason in [({'text':'invented'},'content_quote_mismatch'),
                              ({'source_pointer':'wrong'},'content_quote_mismatch'),
                              ({'end':99999},'content_quote_mismatch')]:
            with self.subTest(change=change):
                broken=deepcopy(g);p=next(n for n in broken['nodes'] if n['id']=='plan')
                p['properties']['content']['summary']['evidence'][0].update(change)
                self.assertEqual(content_sources(broken)['issues'][0]['reason'],reason)
        event['copied_context']=True
        self.assertEqual(content_sources(g)['issues'][0]['reason'],'content_source_not_visible')


if __name__=='__main__':unittest.main()
