"""Relation dependency, evidence cutoff and replay contracts; not accuracy tests."""
import copy
from pathlib import Path
import tempfile
import unittest

from tracker.adapters import normalize
from tracker.jev import DEFAULT_MODEL
from tracker.schema import InputError,digest
from tracker.semantic_extraction import (FileCandidates,Pipeline,generation_request,
    load_extraction,read,windows,write)
from tracker.plan_relations import (audit,build,candidates,execute,path_for,
    relation_request,LIMIT)


def fixture():
    return normalize({'trajectory_format':'devai/1','trajectory':[
        {'step':0,'user_message':'Prepare a report.','agent':{'thought':None,'action':'Read notes'},'environment':'Notes'},
        {'step':1,'user_message':None,'agent':{'thought':'First write a report in Markdown, then convert it to PDF.','action':'Create report.md'},'environment':'Empty file created'},
        {'step':2,'user_message':None,'agent':{'thought':None,'action':'Write report.md'},'environment':'Text inserted'},
        {'step':3,'user_message':None,'agent':{'thought':None,'action':'Convert report.md to report.pdf'},'environment':'ERROR: converter unavailable'},
        {'step':4,'user_message':None,'agent':{'thought':None,'action':'List report.pdf'},'environment':'FUTURE FEEDBACK'}]})[0]


class Provider(FileCandidates):
    def content(self,run,ref,activity):
        req=generation_request(run,ref,activity)
        values={k:{'status':'expressed','text':ref['text'],'evidence':[ref]} for k in req['field_contract']}
        candidate={'fields':values}
        if activity=='plan':
            candidate['plan_structure']={'schema':'local-plan-content/1','organization':'staged',
                'steps':[{'id':'draft','text':'Write the Markdown report.','target':'Report content','evidence':[ref]},
                         {'id':'convert','text':'Convert to PDF.','target':'PDF report','evidence':[ref]}],
                'links':[{'from':'draft','to':'convert','kind':'precedes','evidence':[ref]}],
                'completion_criterion':{'status':'not_expressed'}}
        return {'status':'ready','request_hash':digest(req),'producer':'test fixture','candidates':[candidate]}


def transport(req):
    stage=req['state']['stage'];subject=req['state']['subject']['text']
    if stage=='partition':choice='p0'
    elif stage=='activity':choice='plan' if subject.startswith('First write') else 'construct'
    elif stage=='content':choice='c0'
    elif stage=='plan_stage_correspondence':choice='s1' if subject.startswith(('Convert','List')) else 's0'
    else:choice='prepares' if subject.startswith('Create') else 'checks' if subject.startswith('List') else 'attempts'
    keys=req['questions']['choice']['criteria']
    # The reported label/confidence disagree intentionally; raw maximum wins.
    return {'model':DEFAULT_MODEL,'answers':{'choice':{'type':'choice','choice':'unresolved','confidence':0,
        'probabilities':{k:0.34 if k==choice else 0.66/(len(keys)-1) for k in keys}}}}


class PlanRelationTests(unittest.TestCase):
    def setup_result(self,d):
        run=fixture();engine=Pipeline(d,Provider(Path(d)/'candidates'),transport)
        return run,engine,engine.run(run)

    def test_selected_local_contents_then_stage_then_role_and_source_feedback(self):
        with tempfile.TemporaryDirectory() as d:
            run,engine,extraction=self.setup_result(d)
            calls=engine.calls;result,validation=execute(run,extraction,engine)
            self.assertEqual(engine.calls-calls,8)
            self.assertEqual(result['actions'][0]['status'],'no_prior_selected_plan')
            self.assertEqual([r['type'] for r in result['relations']],
                ['prepares_plan_step','attempts_plan_step','attempts_plan_step','checks_plan_step'])
            self.assertEqual([r['plan_step_id'] for r in result['relations']],['draft','draft','convert','convert'])
            self.assertFalse(validation['completion_inferred'])
            before=engine.calls;execute(run,extraction,engine);self.assertEqual(engine.calls,before)
            view=load_extraction(run,d)
            self.assertEqual(view['validation']['source_feedback_links'],5)
            self.assertEqual(view['validation']['source_expression_links'],1)
            self.assertEqual(len([r for r in view['document']['relations'] if r.get('plan_step_id')]),4)
            self.assertEqual(view['validation']['relations'],10) # source pairs, responses and stage judgments
            for edge in result['relations']:
                saved=read(Path(d)/'decisions'/f"{edge['role_request']}.json")
                req=saved['request'];cutoff=req['state']['subject']['event_id']
                index=next(e['index'] for e in run['events'] if e['id']==cutoff)
                ids={e['id'] for e in req['state']['prefix']}
                self.assertFalse(any(e['id'] in ids for e in run['events'] if e['index']>index))
                self.assertEqual(req['state']['stage_selection_request'],edge['stage_request'])

    def test_rejections_and_multiple_stage_choice_do_not_create_edges_or_call_role(self):
        with tempfile.TemporaryDirectory() as d:
            run,engine,extraction=self.setup_result(d)
            for choice in ['none_of_these','multiple_stages','unresolved']:
                calls=[]
                def choose(req):calls.append(req);return choice,digest(req)
                result=build(run,extraction,choose)
                self.assertEqual(result['relations'],[]);self.assertEqual(len(calls),4)
                self.assertTrue(all(r['state']['stage']=='plan_stage_correspondence' for r in calls))
            incomplete=copy.deepcopy(extraction);incomplete['status']='needs_work'
            with self.assertRaisesRegex(InputError,'Complete local'):build(run,incomplete,engine.choose)

    def test_replay_rejects_tampered_links_and_updated_local_extraction_is_not_silently_reused(self):
        with tempfile.TemporaryDirectory() as d:
            run,engine,extraction=self.setup_result(d);result,_=execute(run,extraction,engine)
            invalid=copy.deepcopy(result);invalid['relations'][0]['type']='attempts_plan_step'
            with self.assertRaisesRegex(InputError,'differ'):audit(run,extraction,invalid,d)
            updated=copy.deepcopy(extraction);updated['note']='new extraction version'
            self.assertNotEqual(path_for(d,updated),path_for(d,extraction))
            write(Path(d)/'results'/f"{run['id']}.json",updated)
            self.assertNotIn('plan_relation_review',load_extraction(run,d)['document'])

    def test_candidate_retrieval_preserves_old_evidence_and_excludes_future_or_other_actors(self):
        with tempfile.TemporaryDirectory() as d:
            run,engine,extraction=self.setup_result(d)
            action=extraction['units'][-1];pool=candidates(run,extraction,action)
            self.assertEqual(len(pool),2)
            req=relation_request(run,extraction,action,pool)
            self.assertIn(pool[0]['plan_source']['event_id'],[e['id'] for e in req['state']['prefix']])
            changed=copy.deepcopy(extraction)
            plan=next(u for u in changed['units'] if u['activity']=='plan');plan['actor']='another_agent'
            self.assertEqual(candidates(run,changed,action),[])
            self.assertEqual(candidates(run,extraction,extraction['units'][0]),[])

    def test_oversized_pool_needs_retrieval_instead_of_silent_negative(self):
        with tempfile.TemporaryDirectory() as d:
            run,engine,extraction=self.setup_result(d)
            plan=next(u for u in extraction['units'] if u['activity']=='plan')
            plan['plan_structure']['steps']*=LIMIT
            def forbidden(req):raise AssertionError('Must not send oversized candidate pool')
            result=build(run,extraction,forbidden)
            self.assertEqual(result['relations'],[])
            self.assertEqual(result['actions'][-1]['status'],'needs_plan_candidate_retrieval')


if __name__=='__main__':unittest.main()
