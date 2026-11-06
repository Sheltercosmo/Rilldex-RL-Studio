"""A context reset must survive work history, correspondence and measurements."""
from copy import deepcopy
from pathlib import Path
import unittest

from rilldex import chat_sessions_document
from tracker.adapters import normalize
from tracker.schema import digest
from tracker.semantic_map import evidence
from tracker.semantic_extraction import read
from tracker.requested_work import build as requested_work
from tracker.work_correspondence import state_before
from tracker.work_lineage import build as lineage
from tracker import declared_work_history, declared_work_actions, revision_metrics


def fixture():
    sessions=[]
    for context, target in [('first','A'),('reset','B')]:
        sessions.append({'trajectory_id':'worker','context_id':context,'messages':[
            {'role':'user','content':f'Write report {target}.'},
            {'role':'assistant','content':f'I will write report {target}.','tool_calls':[
                {'id':'call-1','type':'function','function':{'name':'write','arguments':'{}'}}]},
            {'role':'tool','tool_call_id':'call-1','content':'Saved.'}]})
    run=normalize(chat_sessions_document(sessions))[0]
    units=[{'id':'u-'+e['id'],'source':evidence(run,e['id']),'actor':e['actor'],
            'trajectory_id':e['trajectory_id'],'kind':'action' if e['kind']=='action' else 'semantic',
            'status':'selected','content':{}} for e in run['events'] if e['kind'] in {'instruction','message','action'}]
    doc={'run_id':run['id'],'source_hash':digest(run),'status':'complete_local_extraction','units':units,'relations':[]}
    return run,doc


class WorkContextIsolationTests(unittest.TestCase):
    def build_requested(self):
        run,doc=fixture();seen=[]
        class Provider:
            def get(self,run,req,unit):
                seen.append(req['previous_records'])
                return {'request_hash':digest(req),'producer':'structural test',
                        'candidates':[{'edits':[{'op':'introduce','record_id':'report','kind':'work',
                            'text':unit['source']['text'],'evidence':[unit['source']]}]}]}
        work=requested_work(run,doc,Provider(),lambda req:('c0',digest(req)))
        return run,doc,work,seen

    def test_requested_records_reset_and_ids_remain_local(self):
        run,doc,work,seen=self.build_requested()
        self.assertEqual(seen,[[],[]])
        self.assertEqual(len(work['records']),2)
        self.assertEqual([len(s['state_after']) for s in work['steps']],[1,1])
        actions=[u for u in doc['units'] if u['kind']=='action']
        for action,target in zip(actions,['A','B']):
            snap=state_before(run,doc,work,action)
            self.assertEqual([r['text'] for r in snap['records']],[f'Write report {target}.'])
        doc['requested_work']=work
        projected=lineage(run,doc)
        self.assertEqual(len(projected['records']),2)
        first=projected['records'][0]
        self.assertEqual(first['later_recorded_dispatch_event_ids'],[actions[0]['source']['event_id']])

    def test_new_context_with_no_user_request_does_not_inherit_old_work(self):
        run,doc,work,seen=self.build_requested()
        work=deepcopy(work);work['steps']=work['steps'][:1]
        action=[u for u in doc['units'] if u['kind']=='action'][-1]
        self.assertEqual(state_before(run,doc,work,action)['records'],[])

    def test_declared_work_does_not_join_identical_words_across_reset(self):
        run,doc=fixture()
        statements=[u for u in doc['units'] if u['actor']=='agent' and u['kind']=='semantic']
        local={'status':'complete','source_hash':digest(run),'base_map_hash':digest(doc),'observations':[
            {'unit_id':u['id'],'request':'local','items':[{'id':'w','work':'Write report.',
             'declaration':'commits','evidence':[u['source']]}]} for u in statements]}
        history=declared_work_history.build(run,doc,local,
            lambda req:self.fail('The new context has no earlier visible declared work'))
        self.assertEqual(len(history['records']),2)
        actions=[u for u in doc['units'] if u['kind']=='action']
        pool=declared_work_actions.candidates(run,doc,history,actions[-1])
        self.assertEqual(len(pool),1)
        self.assertEqual(pool[0]['first']['unit_id'],statements[-1]['id'])

    def test_enacted_revision_chain_cannot_cross_reset(self):
        control=read(Path(__file__).parent/'fixtures/revision-context-control.json')
        run,doc=control['run'],control['document']
        self.assertEqual(doc['source_hash'],digest(run))
        self.assertEqual(len(revision_metrics.inspect(run,doc)['episodes']),1)
        row=doc['attempt_revisions']['observations'][0]
        before=next(u for u in doc['units'] if u['id']==row['previous_unit_id'])
        event=next(e for e in run['events'] if e['id']==before['source']['event_id'])
        event['context_id']='old-context'
        responses={o['response_event_id'] for o in doc['operation_outcomes']['observations']
                   if o['action_event_id']==event['id']}
        for e in run['events']:
            if e['id'] in responses:e['context_id']='old-context'
        doc['operation_outcomes']['source_hash']=digest(run)
        self.assertEqual(revision_metrics.inspect(run,doc)['episodes'],[])

    def test_scope_comparison_does_not_report_a_reset_as_changed_terms(self):
        from tracker.scope_context import build
        run,doc,work,_=self.build_requested();doc['requested_work']=work
        actions=[u for u in doc['units'] if u['kind']=='action']
        self.assertFalse(build(run,doc,*actions)['available'])

    def test_declaration_record_candidates_stay_in_their_context(self):
        from tests.test_work_declarations import fixture as declarations_fixture
        from tracker.work_declarations import build
        run,doc=declarations_fixture(['I will write A.','I will write A.'])
        last=doc['units'][-1]
        next(e for e in run['events'] if e['id']==last['source']['event_id'])['context_id']='reset'
        doc['source_hash']=digest(run)
        def decide(req):
            self.assertFalse(req['state'].get('prior_records'))
            return {'choice':{'value':'commits'}},digest(req)
        result=build(run,doc,decide)
        self.assertEqual(len(result['records']),2)

    def test_recovery_checks_do_not_jump_to_another_context(self):
        from tests.test_state_capture import source
        from tracker.work_state import derive
        run=normalize(source(),'swe-agent')[0]
        original=derive(run)
        first=original['episodes'][0];retry=first['retry']
        self.assertIsNotNone(retry)
        start=next(e['index'] for e in run['events'] if e['id']==retry)
        for e in run['events']:
            if e['index']>=start:e['context_id']='reset'
        changed=derive(run)
        self.assertIsNone(changed['episodes'][0]['retry'])
