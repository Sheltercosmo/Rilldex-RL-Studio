from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from tracker import declared_work_actions as actions,declared_work_history as histories
from tracker.schema import digest,InputError
from tracker.semantic_map import evidence
from tracker.semantic_extraction import Pipeline
from tests.test_work_declarations import fixture
from tests.test_declared_work_history import local


def setup():
    run,doc=fixture(['I will write A.','FUTURE_COMPLETION_CLAIM']);source=local(run,doc)
    for i,e in enumerate(e for e in run['events'] if e['kind']=='action'):
        ref=evidence(run,e['id'])
        doc['units'].append({'id':'a'+str(i),'kind':'action','activity':'construct','actor':'agent','trajectory_id':e['trajectory_id'],
            'source':ref,'content':{'summary':{'text':e['text'],'evidence':[ref]},'target':{'text':'Write A.','evidence':[ref]}}})
    source['base_map_hash']=digest(doc)
    history=histories.build(run,doc,source,lambda req:({'choice':{'value':req['state']['prior_records'][0]['id']}},digest(req)))
    return run,doc,source,history


class DeclaredWorkActionsTests(unittest.TestCase):
    def test_record_dispatch_context_is_temporal_and_reviews_bind_exact_relations(self):
        run,doc,source,history=setup()
        doc['relations']=[{'type':'recorded_with','from':'u0','to':'a0'},{'type':'recorded_with','from':'u1','to':'a1'}]
        source['base_map_hash']=digest(doc);history['base_map_hash']=digest(doc);history['local_items_hash']=digest(source)
        current=next(u for u in doc['units'] if u['id']=='a0')
        pool=actions.candidates(run,doc,history,current,actions.DIRECTED_VERSION)
        self.assertEqual([u['unit_id'] for u in pool[0]['recorded_dispatch_context']],['a0'])
        result=actions.build(run,doc,source,history,lambda req:({k:{'value':'attempts'} for k in req['questions']},digest(req)))
        relation=result['relations'][0]
        review={'origin':'implementation-assistant-source-review','source_hash':digest(run),'observation_hash':digest(result),'limitations':'Development only.',
            'notes':[{'kind':'relation_review','relation_ref':{k:relation[k] for k in ('from','to','type','declared_work_id')},'text':'Review scope.'}]}
        self.assertEqual(actions.validate_reviews(run,result,review)['notes'],1)
        review['notes'][0]['relation_ref']['declared_work_id']='wrong-record'
        with self.assertRaisesRegex(InputError,'relation review'):actions.validate_reviews(run,result,review)

    def test_cutoff_preserves_prior_declaration_and_excludes_future_result(self):
        run,doc,source,history=setup();captured=[];before=deepcopy(doc)
        def decide(req):
            captured.append(req);return {k:{'value':'attempts'} for k in req['questions']},digest(req)
        result=actions.build(run,doc,source,history,decide)
        self.assertEqual(doc,before)
        self.assertEqual([r['declaration_at_dispatch'] for r in result['relations']],['commits','reports_finished'])
        self.assertNotIn('FUTURE_COMPLETION_CLAIM',str(captured[0]))
        self.assertNotIn('DO_NOT_USE_FUTURE_RESULT_0',str(captured[0]))
        self.assertNotIn('DO_NOT_USE_FUTURE_DISPATCH_1',str(captured[0]))
        self.assertEqual({r['type'] for r in result['relations']},{'attempts_declared_work'})
        self.assertNotIn('completed',result)

    def test_roles_and_unresolved_are_preserved_without_cross_trajectory_matches(self):
        run,doc,source,history=setup();record=history['records'][0]
        other=deepcopy(record);other.update(id='other',trajectory_id='other-trajectory');history['records'].append(other)
        result=actions.build(run,doc,source,history,lambda req:({k:{'value':'unresolved'} for k in req['questions']},digest(req)))
        self.assertEqual([r['candidate_count'] for r in result['actions']],[1,1]);self.assertEqual(result['relations'],[])
        self.assertTrue(all(set(r['choices'].values())=={'unresolved'} for r in result['actions']))
        result=actions.build(run,doc,source,history,lambda req:({k:{'value':'prepares'} for k in req['questions']},digest(req)))
        self.assertEqual({r['type'] for r in result['relations']},{'prepares_declared_work'})

    def test_changed_dependencies_and_incomplete_model_choices_are_rejected(self):
        run,doc,source,history=setup()
        with self.assertRaisesRegex(InputError,'selections'):actions.build(run,doc,source,history,lambda req:({},digest(req)))
        source['status']='incomplete'
        with self.assertRaisesRegex(InputError,'Complete'):actions.build(run,doc,source,history,lambda _:None)

    def test_exact_replay_uses_argmax_and_does_not_accept_changed_roles(self):
        run,doc,source,history=setup()
        def answer(req):return {'model':req['model'],'answers':{k:{'type':'choice','choice':'none','confidence':0,
            'probabilities':{c:float(c=='checks') for c in q['criteria']}} for k,q in req['questions'].items()}}
        with TemporaryDirectory() as d:
            engine=Pipeline(Path(d),None,answer);result,validation=actions.execute(run,doc,source,history,engine)
            self.assertEqual(validation['relations'],2)
            self.assertEqual({r['type'] for r in result['relations']},{'checks_declared_work'})
            replay=Pipeline(Path(d),None,lambda _:self.fail('Cache should satisfy exact requests'))
            self.assertEqual(actions.execute(run,doc,source,history,replay)[0],result);self.assertEqual(replay.calls,0)
            result['relations'][0]['type']='attempts_declared_work'
            with self.assertRaisesRegex(InputError,'differs'):actions.audit(run,doc,source,history,result,d)


if __name__=='__main__':unittest.main()
