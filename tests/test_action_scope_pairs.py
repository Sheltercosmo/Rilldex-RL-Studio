"""Multi-link scope, source visibility, raw argmax and saved graph contracts."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from tracker import action_targets as targets,action_scope_pairs as pairs
from tracker.schema import InputError,digest
from tracker.semantic_extraction import Pipeline,load_extraction,read
from tests.test_plan_relations import fixture,Provider,transport as base_transport


def transport(req):
    if req['state']['stage']!='action_target_scope_pairs':return base_transport(req)
    return {'model':req['model'],'answers':{
        key:{'type':'choice','choice':'same_work_target','confidence':1,
             'probabilities':{k:.34 if k=='partial_work_overlap' else .66/(len(q['criteria'])-1) for k in q['criteria']}}
        for key,q in req['questions'].items()}}


class ActionScopePairTests(unittest.TestCase):
    def setup_result(self,d):
        run=fixture();engine=Pipeline(d,Provider(Path(d)/'candidates'),transport)
        return run,engine,engine.run(run)

    def test_multiple_overlaps_survive_without_identity_gate_and_replay(self):
        with tempfile.TemporaryDirectory() as d:
            run,engine,x=self.setup_result(d);before=deepcopy(x);calls=engine.calls
            result,validation=targets.execute(run,x,engine,version=targets.PAIRWISE_VERSION)
            self.assertEqual(engine.calls-calls,4)
            self.assertEqual(result['coverage']['compared_pairs'],10)
            self.assertEqual(len(result['relations']),10)
            self.assertTrue(all(r['type']=='overlapping_work_scope' for r in result['relations']))
            self.assertEqual(x,before);self.assertTrue(validation['argmax_replayed'])
            calls=engine.calls;targets.execute(run,x,engine,version=targets.PAIRWISE_VERSION)
            self.assertEqual(engine.calls,calls)
            view=load_extraction(run,d,action_target_version=targets.PAIRWISE_VERSION)
            self.assertEqual(len(view['document']['work_paths']['paths']),5)
            self.assertTrue(view['document']['work_paths']['dispatch_coverage']['each_action_once'])
            for row in result['actions'][1:]:
                req=read(Path(d)/'decisions'/f"{row['request']}.json")['request']
                self.assertNotIn('choice',req['questions'])
                self.assertEqual(set(req['questions']),{r['question_id'] for r in row['pairs']})
                self.assertNotIn('FUTURE FEEDBACK',str(req))
                self.assertNotIn('anchor_selection_request',req['state'])

    def test_batch_siblings_are_not_temporal_predecessors_and_other_actors_stay_out(self):
        with tempfile.TemporaryDirectory() as d:
            run,_,x=self.setup_result(d)
            actions=[u for u in x['units'] if u['kind']=='action'];current=actions[-1]
            events={e['id']:e for e in run['events']}
            events[current['source']['event_id']]['parent_id']='same-batch'
            events[actions[-2]['source']['event_id']]['parent_id']='same-batch'
            actions[0]['actor']='other-agent'
            pool,excluded=pairs.candidate_scope(run,x,current)
            self.assertNotIn(actions[0]['id'],[p['unit_id'] for p in pool])
            self.assertNotIn(actions[-2]['id'],[p['unit_id'] for p in pool])
            self.assertEqual([e['unit_id'] for e in excluded],[actions[-2]['id']])

    def test_all_pair_judgments_remain_but_identity_path_uses_latest_match(self):
        with tempfile.TemporaryDirectory() as d:
            run,engine,x=self.setup_result(d)
            def decide(req):
                return {k:{'value':'same_work_target'} for k in req['questions']},digest(req)
            result=pairs.build(run,x,decide)
            self.assertEqual(len(result['relations']),4)
            self.assertEqual(sum(len(r['pairs']) for r in result['actions']),10)
            actions=[u for u in x['units'] if u['kind']=='action']
            self.assertEqual([(r['from'],r['to']) for r in result['relations']],
                             [(a['id'],b['id']) for b,a in zip(actions,actions[1:])])

    def test_missing_answers_and_capacity_are_not_negative_correspondence(self):
        with tempfile.TemporaryDirectory() as d:
            run,_,x=self.setup_result(d)
            with self.assertRaisesRegex(InputError,'answers differ'):
                pairs.build(run,x,lambda req:({},digest(req)))
            action=x['units'][-1];first=next(u for u in x['units'] if u['kind']=='action')
            x['units']=[{**deepcopy(first),'id':f'dev-{i}'} for i in range(pairs.LIMIT+1)]+[action]
            result=pairs.build(run,x,lambda req:(_ for _ in ()).throw(AssertionError('No over-budget inference')))
            self.assertEqual(result['coverage']['capacity_gap_actions'],1)
            self.assertEqual(result['relations'],[])

    def test_changed_pair_value_or_graph_edge_fails_replay(self):
        with tempfile.TemporaryDirectory() as d:
            run,engine,x=self.setup_result(d)
            result,_=targets.execute(run,x,engine,version=targets.PAIRWISE_VERSION)
            bad=deepcopy(result);bad['actions'][-1]['pairs'][0]['choice']='same_work_target'
            with self.assertRaisesRegex(InputError,'replay'):targets.audit(run,x,bad,d)
            bad=deepcopy(result);bad['relations'][0]['type']='same_action_target'
            with self.assertRaisesRegex(InputError,'replay'):targets.audit(run,x,bad,d)

    def test_source_operation_remains_visible_even_with_broad_work_summary(self):
        with tempfile.TemporaryDirectory() as d:
            run,_,x=self.setup_result(d);action=x['units'][-1]
            action['content']['operation']={'status':'expressed','text':'List report.pdf','evidence':[action['source']]}
            pool,_=pairs.candidate_scope(run,x,action);req=pairs.request(run,action,pool)
            self.assertEqual(req['state']['current_meaning']['operation'],'List report.pdf')
            self.assertIn('broader objective',req['state']['comparison_rule'])

    def test_unresolved_pairs_remain_unknown_in_rollout_metrics_unless_identity_is_positive(self):
        from tracker.rollout_metrics import semantic_record
        for positive_identity in (False,True):
            with self.subTest(positive_identity=positive_identity),tempfile.TemporaryDirectory() as d:
                def decisions(req):
                    if req['state']['stage']!='action_target_scope_pairs':return base_transport(req)
                    selected={k:('same_work_target' if positive_identity and i==0 else 'unresolved')
                              for i,k in enumerate(req['questions'])}
                    return {'model':req['model'],'answers':{
                        k:{'type':'choice','choice':v,'probabilities':{
                            c:1 if c==v else 0 for c in req['questions'][k]['criteria']}}
                        for k,v in selected.items()}}
                run=fixture();engine=Pipeline(d,Provider(Path(d)/'candidates'),decisions)
                x=engine.run(run)
                result,_=targets.execute(run,x,engine,version=targets.PAIRWISE_VERSION)
                view=load_extraction(run,d,action_target_version=targets.PAIRWISE_VERSION)
                statuses={r['status'] for r in result['actions'][1:]}
                self.assertEqual(statuses,{'compared'} if positive_identity else {'unresolved'})
                bundle={**view,'observer':{'id':'scope-pair-test','label':'Scope pair test'}}
                metric=semantic_record(run,bundle)['metrics']['identity_unresolved_fraction']
                self.assertEqual(metric['numerator'],0 if positive_identity else 4)
                self.assertEqual(metric['denominator'],5)
                self.assertGreater(result['coverage']['unresolved_pairs'],0)


if __name__=='__main__':unittest.main()
