import copy
import tempfile
import unittest
from pathlib import Path

from tracker import work_state, recovery_windows, graph_store, analysis_metrics, investigation_plans, monitoring, monitor_evidence
from tracker.adapters import normalize
from tracker.portable import chat_document
from tracker.schema import InputError,digest
from tracker.state_capture import WorkStateRecorder,call_ref,object_version
from tracker.store import Store


def captured(steps):
    """Authored source/state mechanics control; no model judgments."""
    recorder=WorkStateRecorder(environment='record-workflow/1');messages=[{'role':'user','content':'Make the record valid.'}]
    state={'record':0,'auxiliary':0}
    for i,step in enumerate(steps):
        cid='c'+str(i);kind=step['kind'];action=call_ref(cid);result=call_ref(cid,result=True)
        messages.append({'role':'assistant','content':step.get('text','Check the record.' if kind=='check' else 'Update the record.'),
            'tool_calls':[{'id':cid,'type':'function','function':{'name':'validate' if kind=='check' else 'update','arguments':'{}'}}]})
        before=recorder.snapshot(action,{k:object_version(v) for k,v in state.items()})
        if kind=='check':
            messages.append({'role':'tool','tool_call_id':cid,'content':step.get('result','failed')})
            recorder.check(action,result,snapshot=before,criterion_id=step.get('criterion','record-valid'),criterion_version=step.get('version','1'),
                required_objects=step.get('scope',['record']),outcome=step.get('result','failed'),state_stable=step.get('stable',True))
        else:
            state.update(step.get('state',{'record':1}));messages.append({'role':'tool','tool_call_id':cid,'content':'Updated.'})
            after=recorder.snapshot(result,{k:object_version(v) for k,v in state.items()});recorder.edit(action,result,before=before,after=after)
    raw=recorder.attach(chat_document(messages=messages))
    return normalize(raw)[0]


def check(result='failed',**kw):return {'kind':'check','result':result,**kw}
def change(**kw):return {'kind':'change',**kw}
def project(run):return recovery_windows.project(work_state.derive(run),graph_store.build(run))


class RecoveryWindowTests(unittest.TestCase):
    def test_short_failed_retry_is_censored_instead_of_a_negative(self):
        run=captured([check(),change(),check()])
        self.assertEqual(work_state.derive(run)['episodes'][0]['status'],'failed') # Retained legacy definition.
        output=project(run);first=output['records'][0]
        self.assertEqual(first['status'],'unknown');self.assertIn('window_not_fully_observed',first['unknown_reasons'])
        self.assertIsNone(output['metrics']['value']);self.assertEqual(output['metrics']['unknown'],2)

    def test_later_comparable_recovery_is_not_hidden_by_an_incomparable_pass(self):
        run=captured([check(),change(),check('passed',scope=['record','auxiliary']),check('passed')])
        self.assertEqual(work_state.derive(run)['episodes'][0]['status'],'unknown')
        first=project(run)['records'][0];self.assertTrue(first['value']);self.assertTrue(first['window_closed'])
        self.assertEqual(len(first['attempts']),2);self.assertFalse(first['attempts'][0]['comparable'])
        self.assertIn('criterion_input_scope_changed',first['attempts'][0]['issues'])
        self.assertEqual(first['attempts'][1]['changes'][0]['changed_inputs'],['record'])

    def test_three_comparable_failures_close_only_the_complete_opportunity(self):
        output=project(captured([check(),check(),check(),check()]))
        self.assertEqual(output['metrics'],{'value':0,'numerator':0,'denominator':1,'opportunities':4,'unknown':3})
        self.assertEqual(output['records'][0]['status'],'not_recovered_in_window')
        self.assertTrue(output['records'][0]['window_closed']);self.assertEqual(output['records'][0]['unknown_reasons'],[])

    def test_early_recovery_needs_changed_inputs_and_a_retained_recorded_effect(self):
        self.assertTrue(project(captured([check(),change(),check('passed')]))['records'][0]['value'])
        for steps in [[check(),check('passed')],
                      [check(),change(state={'auxiliary':1}),check('passed')],
                      [check(),change(state={'record':1}),change(state={'record':0}),check('passed')]]:
            with self.subTest(steps=steps):
                first=project(captured(steps))['records'][0]
                self.assertIsNone(first['value']);self.assertIn('passing_check_without_supported_change',first['unknown_reasons'])

    def test_changed_definition_stability_and_unknown_outcome_do_not_make_false_negatives(self):
        for options,reason in [({'version':'2'},'criterion_version_changed'),({'stable':None},'input_stability_unestablished'),({'result':'unknown'},'check_result_unknown')]:
            steps=[check(),change(),check(**options),check(**options),check(**options)]
            first=project(captured(steps))['records'][0]
            self.assertIsNone(first['value']);self.assertTrue(first['window_closed']);self.assertIn(reason,first['unknown_reasons'])

    def test_other_criteria_do_not_consume_window_and_fourth_retry_does_not_rescue_it(self):
        run=captured([check(),change(),check('passed',criterion='other'),check('passed')])
        self.assertEqual(len(project(run)['records'][0]['attempts']),1)
        run=captured([check(),check(),check(),check(),change(),check('passed')])
        first=project(run)['records'][0];self.assertFalse(first['value']);self.assertEqual(len(first['attempts']),3)

    def test_private_failure_and_cross_trajectory_checks_are_not_reactions_in_the_lane(self):
        run=captured([check(),change(),check('passed')]);feedback=next(e for e in run['events'] if e['kind']=='feedback')
        feedback['agent_visibility']='not_established'
        out=project(run);self.assertEqual(out['metrics']['opportunities'],0);self.assertEqual(len(out['coverage']['excluded_failures']),1)
        run=captured([check(),change(),check('passed')])
        for e in run['events']:
            if e.get('call_id')=='c2' or e.get('source_call_id')=='c2':e['trajectory_id']='other-lane'
        self.assertIsNone(project(run)['records'][0]['value'])

    def test_missing_capture_and_no_failure_are_unavailable_not_recovery_zero(self):
        run=captured([check(),change(),check('passed')]);run['raw'].pop('work_state')
        self.assertIsNone(project(run)['metrics']['value'])
        self.assertEqual(project(captured([check('passed')]))['metrics']['opportunities'],0)

    def test_dependency_dag_cached_receipt_and_legacy_monitor_survive(self):
        run=captured([check(),change(),check()])
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'db.sqlite');store.add([run])
            old=monitoring.create(store,{'name':'Legacy recovery','kind':'analysis','observer':'source','analysis':{'measure':'criterion_recovery'}})
            new=monitoring.create(store,{'name':'Recovery window','kind':'analysis','observer':'source','analysis':{'measure':'criterion_recovery_window'}})
            self.assertEqual(monitoring.sync(store)['errors'],0)
            old_value=monitoring.values(store,old['id'],{run['id']})[run['id']]
            value=monitoring.values(store,new['id'],{run['id']})[run['id']]
            self.assertEqual(old_value['value'],0);self.assertIsNone(value['value']);self.assertEqual(value['unknown'],2)
            receipt=monitor_evidence.read(store,value['id']);self.assertEqual(len(receipt['explanation']['analysis_cases']),2)
            plan=investigation_plans.read_plan(store,value['analysis']['plan_id'])
            self.assertEqual([n['op'] for n in plan['definition']['nodes']],['work_state','recovery_windows'])
            again=investigation_plans.execute(store,plan['definition'])
            self.assertEqual(again['execution'],{'cache_hits':2,'computed':0,'inference_calls':0})
            self.assertEqual(monitor_evidence.read(store,old_value['id'])['explanation']['value'],0)
            bad=copy.deepcopy(plan['definition']);bad['nodes'][1]['inputs']=[]
            with self.assertRaisesRegex(InputError,'dependency'):investigation_plans.execute(store,bad)

    def test_existing_semantic_reference_and_state_facts_share_one_graph(self):
        from tracker import feedback_assessments as fa
        from tracker.semantic_map import evidence
        from tests.test_feedback_opportunities import graph as semantic_graph
        run=captured([check(),change(text='The recorded validation failed; update the record.'),check('passed')]);units=[]
        for e in run['events']:
            if e['actor']!='agent' or e['kind'] not in {'action','message'} or not e['text'].strip():continue
            ref=evidence(run,e['id']);field={'status':'expressed','text':ref['text'],'evidence':[ref]}
            units.append({'id':'unit-'+e['id'],'source':ref,'actor':e['actor'],'trajectory_id':e['trajectory_id'],
                'kind':'action' if e['kind']=='action' else 'semantic','status':'selected','activity':'inspect' if e['kind']=='action' else 'orient',
                'content':{'summary':field}})
        extraction={'run_id':run['id'],'units':units,'status':'complete_local_extraction'}
        def choose(req):return ('f0' if 'validation failed' in req['state']['subject']['text'] else 'none_of_these'),digest(req)
        observed=fa.build(run,extraction,choose,scope_version=fa.CONTRIBUTION_SCOPE,reference_rule=fa.DIRECT_SET_RULE,
            linkage_version=fa.SOURCE_LINKAGE,evidence_layout=fa.INLINE_EVIDENCE)
        graph=semantic_graph(run,extraction,observed)
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'db.sqlite');store.add([run])
            with store.connect() as c:graph_store.save(c,graph)
            spec=analysis_metrics.definition({'measure':'criterion_recovery_window'})
            plan=analysis_metrics.projection_plan(spec,run['id'],digest(run),graph['id'])
            result=investigation_plans.execute(store,plan)['outputs']['observation']
            self.assertEqual(len(result['records'][0]['feedback_reference_edge_ids']),1)
            combined=graph_store.read(store,result['graph_id'])
            self.assertTrue(set(u['id'] for u in units)<={n['id'] for n in combined['nodes']})
            self.assertTrue(any(n['kind']=='artifact_snapshot' for n in combined['nodes']))
            self.assertTrue(any(e['type']=='assesses' for e in combined['edges']))
            self.assertTrue(any(e['type']=='recorded_recheck_of' for e in combined['edges']))

    def test_investigation_uses_window_comparison_and_preserves_legacy_state(self):
        run=captured([check(),change(),check()])
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'db.sqlite');store.add([run]);g=graph_store.build(run)
            with store.connect() as c:graph_store.save(c,g)
            result=investigation_plans.build(store,[{'id':run['id'],'focus':True,'reference':False}],
                'source',{run['id']:{'id':g['id'],'source_hash':digest(run)}})
            self.assertEqual(result['work']['groups']['focus']['metrics']['recovery']['value'],0)
            self.assertIsNone(result['recovery']['groups']['focus']['metrics']['value'])
            self.assertEqual(result['recovery']['groups']['focus']['metrics']['unknown'],2)
            self.assertEqual(result['inference_calls'],0)


if __name__=='__main__':unittest.main()
