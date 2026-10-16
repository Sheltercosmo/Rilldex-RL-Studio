import copy
from pathlib import Path
import tempfile
import unittest

from tracker.adapters import normalize
from tracker.schema import InputError, digest
from tracker.semantic_extraction import (FileCandidates, Pipeline, audit_result,
    generation_request, read, validate_proposals, windows, write)
from tracker.semantic_map import evidence
from tracker.semantic_plan import VERSION, validate_plan
from tracker.jev import DEFAULT_MODEL
from tracker.store import Store


def fixture():
    return normalize({'trajectory_format':'devai/1','trajectory':[
        {'step':0,'user_message':'Prepare the report.', 'agent':{
            'thought':'First write the Markdown report; then convert it to PDF.',
            'action':"Running Python code interactively: create_file('report.md')"},
         'environment':'Created report.md'},
        {'step':1,'user_message':None,'agent':{'thought':'The report is now complete.','action':None},'environment':None}]})[0]


def candidate(run):
    window=windows(run)[0];ref=evidence(run,window['event_id'],start=window['start'],end=window['end']);req=generation_request(run,ref,'plan')
    def field(text):return {'status':'expressed','text':text,'evidence':[ref]}
    plan={'schema':VERSION,'organization':'staged','steps':[
        {'id':'draft','text':'Write the report in Markdown.','target':'Markdown report','evidence':[ref]},
        {'id':'convert','text':'Convert the report to PDF.','target':'PDF report','evidence':[ref]}],
        'links':[{'from':'draft','to':'convert','kind':'precedes','evidence':[ref]}],
        'completion_criterion':{'status':'not_expressed'}}
    fields={k:field('Prepare the report by drafting Markdown then converting it to PDF.') for k in req['field_contract']}
    return req,{'request_hash':digest(req),'producer':'test fixture','candidates':[{'fields':fields,'plan_structure':plan}]}


class PlanTests(unittest.TestCase):
    def test_devai_import_keeps_thought_action_feedback_and_missing_native_arguments(self):
        run=fixture();thought,action,feedback=run['events'][1:4]
        self.assertEqual(action['parent_id'],thought['id'])
        self.assertEqual(action['call_id'],feedback['source_call_id'])
        self.assertEqual(action['source_pointer'],'/trajectory/0/agent/action')
        self.assertFalse(action['arguments_available'])
        self.assertNotIn('exit_code',feedback)
        self.assertNotIn('checkpoint',run['metadata'])
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(len(Store(Path(d)/'store.sqlite').add([run])),1)
        bad=copy.deepcopy(run['raw']);bad['trajectory'][1]['step']=0
        with self.assertRaisesRegex(InputError,'distinct integer'):normalize(bad)

    def test_plan_content_is_stage_addressable_and_never_claims_execution(self):
        run=fixture();req,answer=candidate(run)
        validate_proposals(run,req,answer)
        plan=answer['candidates'][0]['plan_structure']
        for mutate in [lambda p:p['steps'][0].update(status='completed'),
                       lambda p:p['links'][0].update(to='missing'),
                       lambda p:p['links'].append({'from':'convert','to':'draft','kind':'precedes','evidence':[req['source']]})]:
            invalid=copy.deepcopy(plan);mutate(invalid)
            with self.assertRaises(InputError):validate_plan(invalid,lambda a:None)
        future=copy.deepcopy(answer)
        future['candidates'][0]['plan_structure']['steps'][0]['evidence']=[evidence(run,run['events'][-1]['id'])]
        with self.assertRaisesRegex(InputError,'Future evidence'):validate_proposals(run,req,future)
        orient=generation_request(run,req['source'],'orient');wrong=copy.deepcopy(answer);wrong['request_hash']=digest(orient)
        with self.assertRaisesRegex(InputError,'structure differs'):validate_proposals(run,orient,wrong)

    def test_plan_structure_survives_selection_export_and_tamper_check(self):
        run=fixture();req,answer=candidate(run)
        def transport(r):
            choice={'partition':'p0','activity':'plan','content':'c0'}[r['state']['stage']]
            return {'model':DEFAULT_MODEL,'answers':{'choice':{'type':'choice','probabilities':{k:int(k==choice) for k in r['questions']['choice']['criteria']}}}}
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);provider=FileCandidates(root/'candidates')
            write(root/'candidates/responses'/f'{digest(req)}.json',answer)
            engine=Pipeline(root,provider,transport)
            result=engine.run(run,window_ids=[windows(run)[0]['id']])
            self.assertEqual(len(result['units']),1)
            self.assertEqual(len(result['units'][0]['plan_structure']['steps']),2)
            self.assertEqual(audit_result(run,result,root)['coverage'],'selected windows only')
            changed=copy.deepcopy(result);changed['units'][0]['plan_structure']['steps'][0]['target']='Another report'
            with self.assertRaisesRegex(InputError,'Selected plan structure differs'):audit_result(run,changed,root)
            engine.run(run,window_ids=[windows(run)[0]['id']]);self.assertEqual(engine.calls,3)

    def test_explicit_context_scope_preserves_instructions_and_rejects_omitted_citations(self):
        run=fixture();ref=evidence(run,run['events'][-1]['id'])
        req=generation_request(run,ref,'orient',{'schema':'instructions-and-recent/1','recent_events':1})
        self.assertEqual([e['id'] for e in req['prefix']],[run['events'][0]['id'],ref['event_id']])
        self.assertIn(run['events'][1]['id'],req['omitted_context_event_ids'])
        fields={k:{'status':'not_expressed'} for k in req['field_contract']}
        fields['summary']={'status':'expressed','text':'Reports completion.','evidence':[evidence(run,run['events'][1]['id'])]}
        response={'request_hash':digest(req),'producer':'test','candidates':[{'fields':fields}]}
        with self.assertRaisesRegex(InputError,'omitted context'):validate_proposals(run,req,response)

    def test_tied_argmax_replays_after_sorted_json_storage(self):
        from tracker.semantic_extraction import request
        run=fixture();ref=windows(run)[0]
        req=request(run,ref,'partition','Choose.',{'p0':'Complete source','no_suitable_candidate':'Repair','unresolved':'Unknown'})
        def transport(r):
            return {'model':DEFAULT_MODEL,'answers':{'choice':{'type':'choice','probabilities':{'p0':0.4,'no_suitable_candidate':0.4,'unresolved':0.2}}}}
        with tempfile.TemporaryDirectory() as d:
            engine=Pipeline(d,FileCandidates(Path(d)/'candidates'),transport)
            self.assertEqual(engine.choose(req)[0],'p0')
            restored=read(Path(d)/'decisions'/f'{digest(req)}.json')['request']
            self.assertEqual(engine.choose(restored)[0],'p0')
            self.assertEqual(engine.calls,1)


if __name__=='__main__':unittest.main()
