"""Structural engineering contracts, not semantic-accuracy tests."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tracker import analysis_contracts, graph_store, investigation_plans as plans
from tracker.adapters import normalize
from tracker.portable import chat_document, generation_document, Episode
from tracker.schema import InputError, digest, dumps
from tracker.store import Store


class AnalysisContractTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.store=Store(Path(folder.name)/'tracker.sqlite')
        self.run=normalize(generation_document('Compute 2+2.', '2+2=4.'))[0]
        self.store.add([self.run]);self.graph=graph_store.build(self.run)
        with self.store.connect() as c:graph_store.save(c,self.graph)

    def node(self,name='a',op='sequence',run=None,graph=None):
        run=run or self.run;graph=graph or self.graph
        return dict(name=name,op=op,inputs=[],params=dict(run_id=run['id'],source_hash=digest(run),graph_id=graph['id']))

    def plan(self,*nodes):
        return {'schema':plans.VERSION,'nodes':list(nodes or [self.node()])}

    def counts(self):
        with self.store.connect() as c:
            return {t:c.execute('SELECT count(*) FROM '+t).fetchone()[0]
                    for t in ('runs','rollout_graphs','investigation_nodes','investigation_plans')}

    def test_every_executable_operation_declares_meaning_version_and_cost(self):
        catalog=plans.catalog()
        self.assertEqual({r['id'] for r in catalog['operations']},set(plans.OPS))
        for row in catalog['operations']:
            self.assertEqual(row['implementation_version'],plans.OPS[row['id']])
            self.assertEqual(row['new_model_calls'],0)
            self.assertTrue(row['grain'] and row['boundary'] and row['validation'])
        catalog['operations'][0]['evidence_needs'].append('corruption')
        self.assertNotIn('corruption',plans.catalog()['operations'][0]['evidence_needs'])

    def test_source_only_reasoning_stays_unknown_not_zero_or_ready(self):
        result=plans.preflight(self.store,self.plan(self.node(),self.node('work','work_episodes')))
        self.assertTrue(result['valid']);self.assertFalse(result['persisted'])
        self.assertEqual(result['nodes'][0]['missing_evidence'],['semantic_units'])
        self.assertIn('native_actions',result['nodes'][1]['missing_evidence'])
        self.assertEqual(result['new_model_calls'],0)
        self.assertNotIn('value',result['nodes'][0])

    def test_preflight_has_no_projection_or_database_writes(self):
        before=self.counts()
        with patch.object(plans.behavior_sequences,'project',side_effect=AssertionError('Unexpected execution')):
            plans.preflight(self.store,self.plan())
        self.assertEqual(before,self.counts())

    def test_inventory_uses_evidence_not_framework_name(self):
        doc=chat_document([{'role':'user','content':'Read a record.'},
            {'role':'assistant','content':'Read it.','tool_calls':[{'id':'c','type':'function','function':{'name':'read','arguments':'{}'}}]},
            {'role':'tool','tool_call_id':'c','content':'Record available.'}])
        run=normalize(doc)[0];g=graph_store.build(run)
        a=analysis_contracts.inventory(run,g)
        run['metadata']['framework']='some future RL trainer'
        self.assertEqual(a,analysis_contracts.inventory(run,g))
        self.assertEqual(a['native_actions'],1);self.assertEqual(a['linked_text_feedback'],1)
        self.assertEqual(a['software_repair_profile'],0)
        env=normalize(Episode(goal='Reach the goal.').reset(0).gym_step(1,(1,0,True,False,{})).snapshot())[0]
        self.assertEqual(analysis_contracts.inventory(env,graph_store.build(env))['native_actions'],1)

    def test_private_or_copied_feedback_is_not_visible_opportunity(self):
        run=normalize(chat_document([{'role':'assistant','content':None,'tool_calls':[{'id':'c','type':'function','function':{'name':'read','arguments':'{}'}}]},
            {'role':'tool','tool_call_id':'c','content':'Private.'}]))[0]
        feedback=next(e for e in run['events'] if e['kind']=='feedback')
        feedback['agent_visibility']='not_established'
        self.assertEqual(analysis_contracts.inventory(run,graph_store.build(run))['linked_text_feedback'],0)

    def test_invalid_later_binding_cannot_leave_earlier_cache_entries(self):
        broken=self.node('later');broken['params']['source_hash']='wrong'
        before=self.counts()
        with self.assertRaisesRegex(InputError,'binding'):plans.execute(self.store,self.plan(self.node(),broken))
        self.assertEqual(before,self.counts())

    def test_comparison_population_and_dependency_errors_precede_execution(self):
        bad={'name':'compare','op':'compare_sequences','inputs':['a'],
             'params':{'focus':[self.run['id']],'reference':[self.run['id']]}}
        before=self.counts()
        with self.assertRaisesRegex(InputError,'overlap'):plans.execute(self.store,self.plan(self.node(),bad))
        self.assertEqual(before,self.counts())
        bad['params']['reference']=[];bad['inputs']=['a','a']
        with self.assertRaisesRegex(InputError,'Duplicate'):plans.preflight(self.store,self.plan(self.node(),bad))

    def test_recovery_graph_cannot_differ_from_state_dependency(self):
        other=normalize(generation_document('Other.', 'Different.'))[0];self.store.add([other]);g=graph_store.build(other)
        with self.store.connect() as c:graph_store.save(c,g)
        recovery={'name':'r','op':'recovery_windows','inputs':['state'],'params':{'graph_id':g['id']}}
        with self.assertRaisesRegex(InputError,'binding'):
            plans.preflight(self.store,self.plan(self.node('state','work_state'),recovery))

    def test_cache_replay_preserves_identity_and_rechecks_source(self):
        plan=self.plan();a=plans.execute(self.store,plan);b=plans.execute(self.store,plan)
        self.assertEqual(a['id'],b['id']);self.assertEqual(b['execution']['cache_hits'],1)
        damaged=copy.deepcopy(self.run);damaged['metadata']['tampered']=True
        with self.store.connect() as c:c.execute('UPDATE runs SET document=? WHERE id=?',(dumps(damaged),self.run['id']))
        with self.assertRaisesRegex(InputError,'binding'):plans.execute(self.store,plan)

    def test_relation_query_is_source_bound_cached_and_keeps_missing_unknown(self):
        from tracker import graph_queries
        query=copy.deepcopy(graph_queries.PRESETS['assessment_of_inspection_feedback'])
        n=self.node(op='relation_query');n['params']['query']=query
        before=self.counts();pre=plans.preflight(self.store,self.plan(n))
        self.assertEqual(before,self.counts());self.assertEqual(pre['nodes'][0]['missing_evidence'],['semantic_units'])
        result=plans.execute(self.store,self.plan(n));output=result['outputs']['a']
        self.assertEqual(output['anchors'],0);self.assertIsNone(output['behavior_rate'])
        self.assertIsNone(output['recorded_match_fraction'])
        replay=plans.execute(self.store,self.plan(n));self.assertEqual(result['id'],replay['id'])
        self.assertEqual(replay['execution']['cache_hits'],1)
        n['params']['query']['within_units']=1
        self.assertNotEqual(result['id'],plans.execute(self.store,self.plan(n))['id'])

    def test_relation_query_rejects_invalid_predicate_before_any_execution(self):
        from tracker import graph_queries
        n=self.node('query','relation_query');n['params']['query']=copy.deepcopy(graph_queries.PRESETS['assessment_of_inspection_feedback'])
        n['params']['query']['evidence_path']['hops'][0]['direction']='execute-python'
        before=self.counts()
        with self.assertRaises(InputError):plans.execute(self.store,self.plan(self.node(),n))
        self.assertEqual(before,self.counts())

    def test_relation_query_runs_without_actions_on_supplied_reasoning_units(self):
        from tracker import graph_queries
        run=normalize(generation_document('Check the claim.','Claim. Check it. It holds.'))[0]
        self.store.add([run]);g=graph_store.build(run);event=run['events'][-1]
        for uid,start,end,activity in [('claim',0,6,'reference:claim'),('check',7,16,'reference:intention'),('implementation',17,25,'reference:reasoning')]:
            g['nodes'].append({'id':uid,'kind':'unit','activity':activity,'event_index':event['index'],
                'trajectory_id':event['trajectory_id'],'properties':{'actor':'agent','kind':'semantic','status':'selected',
                    'source':{'event_id':event['id'],'start':start,'end':end,'text':event['text'][start:end]}}})
        for a,b,kind in [('implementation','check','implements_text'),('check','claim','intends_check')]:
            edge={'source':a,'target':b,'type':kind,'properties':{}}
            g['edges'].append({'id':'edge-'+digest(edge),**edge})
        g.pop('id');g['nodes'].sort(key=lambda n:n['id']);g['edges'].sort(key=lambda e:e['id']);g={'id':'graph-'+digest(g),**g}
        with self.store.connect() as c:graph_store.save(c,g)
        n=self.node(op='relation_query',run=run,graph=g)
        n['params']['query']={'schema':graph_queries.PATH_VERSION,'question':'Which supplied claims have an intention and implementation?',
            'anchor_activity':'reference:claim','relation':'implements_text','within_units':2,'require_new_exploration':False,
            'evidence_path':{'start':'relation_target','hops':[{'direction':'outgoing','relations':['intends_check']}]}}
        pre=plans.preflight(self.store,self.plan(n));self.assertEqual(pre['nodes'][0]['recorded_counts']['native_actions'],0)
        output=plans.execute(self.store,self.plan(n))['outputs']['a']
        self.assertEqual(output['matched_anchors'],1);self.assertIsNone(output['behavior_rate'])
        self.assertEqual(output['cases'][0]['matches'][0]['evidence_path']['node_ids'],['check','claim'])
        n['params']['query']['within_units']=1
        missing=plans.execute(self.store,self.plan(n))['outputs']['a']
        self.assertEqual(missing['matched_anchors'],0);self.assertIsNone(missing['behavior_rate'])


if __name__=='__main__':unittest.main()
