"""Authored declaration controls, not semantic or real-training reference labels."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from tracker import declared_plans as plans, monitoring, monitor_evidence, measurement_reviews
from tracker.adapters import normalize
from tracker.portable import chat_document
from tracker.schema import digest
from tracker.store import Store


def fixture(lists, tool='write_todos', encoding='chat', step=1):
    args=[]
    for items in lists:
        if isinstance(items, dict): args.append(items); continue
        args.append({'todos':[{'content':text,'status':status} for text,status in items]} if tool=='write_todos'
            else {'command':'plan','task_list':[{'title':text,'status':{'pending':'todo','in_progress':'in_progress','completed':'done'}[status]} for text,status in items]})
    if encoding=='chat':
        messages=[{'role':'user','content':'Inspect the issue, fix it, and check the result.'}]
        for i,a in enumerate(args):
            messages.append({'role':'assistant','content':None,'tool_calls':[{'id':str(i),'type':'function','function':{'name':tool,'arguments':a}}]})
            messages.append({'role':'tool','tool_call_id':str(i),'content':'Recorded tool response.'})
        doc=chat_document(messages)
    else:
        doc={'schema_version':'ATIF-v1.6','agent':{'name':'authored-control'},'steps':[{'step_id':i+1,'source':'agent','message':'',
            'tool_calls':[{'tool_call_id':str(i),'function_name':tool,'arguments':a}]} for i,a in enumerate(args)]}
    run=normalize(doc)[0]
    run['metadata'].update(experiment='authored-structured-plan-controls',training_step=step,training_step_basis='authored_control_index')
    run['id']=digest(run)[:24]
    return run


class DeclaredPlanTests(unittest.TestCase):
    def test_native_profiles_and_encodings_have_same_reported_status_history(self):
        for tool in plans.PROFILES:
            for encoding in ('chat','atif'):
                with self.subTest(tool=tool,encoding=encoding):
                    run=fixture([[('Inspect','completed'),('Fix','in_progress')],[('Inspect','in_progress'),('Fix','completed')],
                        [('Inspect','completed'),('Fix','completed')]],tool,encoding)
                    original=deepcopy(run); result=plans.project(run)
                    self.assertEqual(result['metrics'],dict(value=.5,numerator=1,denominator=2,opportunities=2,unknown=0))
                    graph=plans.evidence_graph(run,result)
                    self.assertEqual(run,original)
                    self.assertEqual(len([e for e in graph['edges'] if e['type']=='updates_declared_plan']),2)
                    self.assertFalse(any(n['kind']=='unit' for n in graph['nodes']))
                    for event in run['events']:
                        self.assertEqual(next(n['properties'] for n in graph['nodes'] if n['id']=='event:'+event['id']),event)

    def test_drop_rename_duplicate_and_malformed_write_remain_unknown(self):
        cases=[([], 'item_not_retained'),([('Inspect again','pending')],'item_not_retained'),
            ([('Inspect','pending'),('Inspect','completed')],'duplicate_item_text')]
        for after,reason in cases:
            result=plans.project(fixture([[('Inspect','completed')],after]))
            self.assertEqual(result['metrics']['unknown'],1)
            self.assertEqual(result['records'][0]['reason'],reason)
        result=plans.project(fixture([[('Inspect','completed')],{'todos':'malformed'},[('Inspect','pending')]]))
        self.assertEqual(result['records'][0]['reason'],'intervening_invalid_declaration')
        self.assertEqual(result['coverage']['invalid_declarations'],1)

    def test_empty_list_counts_as_declaration_but_absent_source_is_unavailable(self):
        result=plans.project(fixture([[]]))
        self.assertEqual(plans.measure(result,'updates')['value'],1)
        self.assertIsNone(plans.measure(result,'reopened')['value'])
        result=plans.project(fixture([]))
        self.assertIsNone(plans.measure(result,'updates')['value'])

    def test_initial_reported_completion_is_separate_from_reopening(self):
        run=fixture([[('Inspect','completed'),('Fix','in_progress')],[('Inspect','completed'),('Fix','completed')]])
        result=plans.measure(plans.project(run),'initial_completed')
        self.assertEqual((result['value'],result['denominator']),(.5,2))
        run=fixture([{'todos':'bad'},[('Inspect','completed')]])
        result=plans.measure(plans.project(run),'initial_completed')
        self.assertEqual((result['value'],result['unknown']),(None,1))

    def test_openhands_view_does_not_change_history_and_defaults_are_explicit(self):
        run=fixture([{'command':'plan','task_list':[{'title':'Inspect','status':'done'}]},
            {'command':'view'}, {'command':'plan','task_list':[{'title':'Inspect'}]}],'task_tracker')
        result=plans.project(run)
        self.assertEqual(result['metrics']['value'],1)
        self.assertEqual(len(result['snapshots']),2)
        self.assertEqual(result['snapshots'][-1]['items'][0]['status_basis'],'documented_profile_default')

    def test_context_trajectory_copy_and_parallel_boundaries(self):
        for change in ({'context_id':'other'}, {'trajectory_id':'other'}, {'copied_context':True}):
            run=fixture([[('Inspect','completed')],[('Inspect','pending')]])
            [e for e in run['events'] if e['kind']=='action'][-1].update(change)
            self.assertEqual(plans.project(run)['metrics']['opportunities'],0)
        run=fixture([[('Inspect','completed')],[('Inspect','pending')]])
        actions=[e for e in run['events'] if e['kind']=='action'];actions[-1]['parent_id']=actions[0]['parent_id']
        result=plans.project(run)
        self.assertEqual(result['records'][0]['reason'],'unordered_declarations')
        self.assertEqual(result['coverage']['unordered_declarations'],2)

    def test_duplicate_previous_text_and_exact_text_boundary(self):
        result=plans.project(fixture([[('Inspect','completed'),('Inspect','completed')],[('Inspect','pending')]]))
        self.assertEqual(result['metrics']['unknown'],2)
        result=plans.project(fixture([[('Inspect','completed')],[('inspect','pending')]]))
        self.assertEqual(result['metrics']['unknown'],1)

    def test_monitor_receipt_replay_and_review_preserve_structured_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'db.sqlite')
            run=fixture([[('Inspect','completed')],[('Inspect','pending')]],'task_tracker','atif')
            store.add([run])
            monitor=monitoring.create(store,dict(name='Reopened reports',kind='analysis',observer='source',
                analysis={'measure':'declared_plan_reopen_fraction'},group='Behavior'))
            monitoring.sync(store)
            value=monitoring.values(store,monitor['id'],{run['id']})[run['id']]
            self.assertEqual(value['value'],1)
            receipt=monitor_evidence.read(store,value['id'])
            self.assertEqual(receipt['graph']['observer'],plans.VERSION)
            self.assertEqual(receipt['explanation']['analysis_cases'][0]['declared_plan_change']['before']['text'],'Inspect')
            sample=measurement_reviews.create(store,dict(monitor_id=monitor['id'],run_ids=[run['id']],size=10,seed='fixed'))
            case=measurement_reviews.case_view(store,sample['id'],sample['cases'][0]['id'])
            self.assertNotIn('prediction',case)
            actions=[e for e in case['source_events'] if e['kind']=='action']
            self.assertEqual(actions[-1]['arguments']['task_list'][0]['title'],'Inspect')


if __name__=='__main__': unittest.main()
