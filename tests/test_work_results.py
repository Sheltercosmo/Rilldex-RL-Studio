from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tracker.adapters import normalize
from tracker import work_results as results
from tracker.schema import digest,InputError
from tracker.semantic_map import evidence
from tracker.semantic_extraction import Pipeline


def fixture(work='Write content to report.md.',command="write('report.md', content)",response='File updated.',*,plan=False):
    run=normalize({'trajectory_format':'devai/1','trajectory':[
        {'step':0,'agent':{'thought':'I will '+work,'action':command},'environment':response},
        {'step':1,'agent':{'thought':'FUTURE_COMPLETION_CLAIM','action':'FUTURE_DISPATCH'},'environment':'FUTURE_FEEDBACK'}]})[0]
    units=[]
    for e in run['events']:
        ref=evidence(run,e['id']);kind='semantic' if e['kind']=='reasoning' else e['kind']
        units.append({'id':'u'+e['id'],'source':ref,'kind':kind,'actor':e['actor'],'trajectory_id':e['trajectory_id'],
                      'activity':'orient' if kind=='semantic' else kind,
                      'content':{'summary':{'text':e['text'],'evidence':[ref]},'target':{'text':work,'evidence':[ref]}}})
    anchor,action,response_unit=units[:3]
    doc={'source_hash':digest(run),'units':units,'relations':[{'from':response_unit['id'],'to':action['id'],'type':'feedback_for'}]}
    rel={'from':action['id'],'to':anchor['id'],'type':'attempts_declared_work','work_text':work,'declared_work_id':'w'}
    context={'id':'w','latest':{'unit_id':anchor['id'],'work':work,'evidence':[anchor['source']]}}
    if plan:
        anchor['plan_structure']={'steps':[{'id':'s','text':work,'target':work,'evidence':[anchor['source']]}],
                                  'completion_criterion':{'status':'not_expressed'}}
        doc['relations'].append({'from':action['id'],'to':anchor['id'],'type':'attempts_plan_step','plan_step_id':'s'})
    matches={'source_hash':digest(run),'base_map_hash':digest(doc),'actions':[{'action_unit_id':action['id'],'record_snapshots':[context]}],'relations':[rel]}
    return run,doc,matches


class WorkResultsTests(unittest.TestCase):
    def test_review_is_bound_to_raw_selection_and_does_not_replace_it(self):
        run,doc,matches=fixture()
        result=results.build(run,doc,matches,lambda req:({'result':{'value':'partial'},'unmet_condition':{'value':'not_reported'}},digest(req)))
        review={'source_hash':digest(run),'observation_hash':digest(result),'notes':[{'result_id':result['observations'][0]['id'],'text':'Unsupported selection.'}]}
        projected=results.project(doc,result,review)
        self.assertEqual(projected['work_results']['observations'][0]['result'],'partial')
        self.assertEqual(projected['work_results']['observations'][0]['review_notes'],review['notes'])
        self.assertTrue(projected['relations'][-1]['work_result_review'])
        self.assertNotIn('review_notes',result['observations'][0])
        review['notes'][0]['result_id']='another-result'
        with self.assertRaisesRegex(InputError,'reference'):results.project(doc,result,review)

    def test_response_cutoff_and_named_scope_without_future_completion_claims(self):
        run,doc,matches=fixture(plan=True);requests=[]
        def decide(req):requests.append(req);return {'result':{'value':'fulfilled'},'unmet_condition':{'value':'not_reported'}},digest(req)
        before=deepcopy(doc);result=results.build(run,doc,matches,decide)
        self.assertEqual(doc,before);self.assertEqual(len(result['observations']),2)
        self.assertNotIn('FUTURE_',str(requests))
        self.assertEqual({r['scope_kind'] for r in result['observations']},{'declared_work','plan_stage'})
        projected=results.project(doc,result)
        self.assertEqual(projected['units'],doc['units'])
        self.assertEqual(len(projected['relations']),len(doc['relations'])+2)

    def test_preparations_and_checks_do_not_become_work_fulfillment(self):
        run,doc,matches=fixture();matches['relations'][0]['type']='prepares_declared_work'
        self.assertEqual(results.pairs(run,doc,matches),[])
        matches['relations'][0]['type']='checks_declared_work'
        self.assertEqual(results.pairs(run,doc,matches),[])

    def test_source_dependencies_and_participant_boundaries_are_checked(self):
        run,doc,matches=fixture();matches['source_hash']='wrong'
        with self.assertRaisesRegex(InputError,'dependencies'):results.pairs(run,doc,matches)
        matches['source_hash']=digest(run);doc['units'][0]['actor']='user';matches['base_map_hash']=digest(doc)
        with self.assertRaisesRegex(InputError,'participant'):results.pairs(run,doc,matches)

    def test_duplicate_scope_pairs_are_rejected_and_absent_responses_stay_absent(self):
        run,doc,matches=fixture();matches['relations'].append(deepcopy(matches['relations'][0]))
        with self.assertRaisesRegex(InputError,'Duplicate'):results.pairs(run,doc,matches)
        matches['relations'].pop();run['events']=[e for e in run['events'] if e['kind']!='feedback']
        doc['source_hash']=digest(run);matches['source_hash']=digest(run);matches['base_map_hash']=digest(doc)
        self.assertEqual(results.pairs(run,doc,matches),[])

    def test_raw_argmax_cache_and_tamper_rejection(self):
        run,doc,matches=fixture()
        def answer(req):return {'model':req['model'],'answers':{name:{'type':'choice','choice':next(iter(question['criteria'])),'confidence':1,
                'probabilities':{k:float(k==('not_established' if name=='result' else 'not_reported')) for k in question['criteria']}} for name,question in req['questions'].items()}}
        with TemporaryDirectory() as root:
            engine=Pipeline(Path(root),None,answer);result,_=results.execute(run,doc,matches,engine)
            self.assertEqual(result['observations'][0]['result'],'not_established')
            replay=Pipeline(Path(root),None,lambda _:self.fail('Exact decisions should be cached'))
            self.assertEqual(results.execute(run,doc,matches,replay)[0],result);self.assertEqual(replay.calls,0)
            result['observations'][0]['result']='fulfilled'
            with self.assertRaisesRegex(InputError,'replay'):results.audit(run,doc,matches,result,root)
