import copy
import tempfile
import unittest
from pathlib import Path
from tracker.adapters import normalize
from tracker.rollout_metrics import source_record, semantic_record, report, training_series, record_map
from tracker.schema import digest, InputError
from tracker.store import Store
from test_tracker import harbor


class RolloutMetricsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name)/'metrics.sqlite')

    def run_fixture(self,step=0,**meta):
        return normalize(harbor(),'harbor',{'experiment':'trial','training_step':step,**meta})[0]

    def test_zero_step_without_checkpoint_is_a_real_training_coordinate(self):
        run=self.run_fixture();self.store.add([run]);r=report(self.store)
        series=training_series(r,'actions')
        self.assertEqual(series['cohorts'][0]['points'][0]['training_step'],0)
        self.assertIsNone(series['cohorts'][0]['points'][0]['policy_version'])
        self.assertEqual(r['training_coordinate_count'],1)

    def test_v19_session_links_refresh_without_rewriting_old_measurements(self):
        from tracker import rollout_metrics as metrics, graph_store
        from test_source_evidence import chat
        run = chat([
            {'role':'assistant','content':'', 'tool_calls':[{'id':'a','type':'function','function':{'name':'read','arguments':'{}'}}]},
            {'role':'tool','tool_call_id':'a','content':'first receipt'},
            {'role':'assistant','content':'', 'tool_calls':[{'id':'b','type':'function','function':{'name':'read','arguments':'{}'}}]},
            {'role':'tool','tool_call_id':'b','content':'second receipt'}])
        for event in run['events']:
            event['context_id'] = 'first' if event['index'] < 3 else 'second'
            if event.get('call_id'): event['call_id'] = 'reused'
            if event.get('source_call_id'): event['source_call_id'] = 'reused'
        self.store.add([run])
        old=metrics.source_record(run);old['schema']='rollout-behavior/19'
        old['metrics']['feedback_link_rate']=metrics.measurement(numerator=0,denominator=2)
        with self.store.connect() as c:
            c.execute('DELETE FROM rollout_measurements')
            c.execute('DELETE FROM graph_edges');c.execute('DELETE FROM graph_nodes');c.execute('DELETE FROM rollout_graphs')
            metrics.save(c,old,created_at='2026-10-01T00:00:00+00:00')
        result=metrics.report(self.store)
        current=result['rows'][0]
        self.assertEqual(current['metrics']['feedback_link_rate']['value'],1.0)
        with self.store.connect() as c:
            import json
            stored=json.loads(c.execute("SELECT document FROM rollout_measurements WHERE json_extract(document,'$.schema')='rollout-behavior/19'").fetchone()[0])
            self.assertEqual(stored,old)
        graph=graph_store.read(self.store,graph_store.build(run)['id'])
        self.assertEqual(sum(e['type']=='response_to' for e in graph['edges']),2)
        self.assertEqual(metrics.ensure_current(self.store),0)

    def test_v6_observations_upgrade_additively_and_keep_annotation_identity(self):
        from tracker.rollout_metrics import save, VERSION
        run=self.run_fixture();self.store.add([run])
        old=source_record(run);old['schema']='rollout-behavior/6';old['observer']='test-v6'
        old['observation_kind']='semantic';old['annotation_hash']='preserved'
        del old['metrics']['recorded_reward']
        with self.store.connect() as c: save(c,old)
        current=next(r for r in report(self.store)['rows'] if r['observer']=='test-v6')
        self.assertEqual(current['schema'],VERSION)
        self.assertEqual(current['annotation_hash'],'preserved')
        self.assertEqual(current['metrics']['actions'],old['metrics']['actions'])
        self.assertIsNone(current['metrics']['recorded_reward']['value'])
        report(self.store)
        with self.store.connect() as c:
            self.assertEqual(c.execute("SELECT count(*) FROM rollout_measurements WHERE observer='test-v6'").fetchone()[0],2)

    def test_metric_projection_preserves_full_report_and_evidence(self):
        from tracker.rollout_metrics import metric_view
        self.store.add([self.run_fixture()]);full=report(self.store)
        before=copy.deepcopy(full);view=metric_view(full,'agent_text_chars')
        self.assertEqual(full,before)
        self.assertEqual(view['report_hash'],full['report_hash'])
        self.assertEqual(set(view['rows'][0]['metrics']),{'agent_text_chars'})
        self.assertEqual(view['rows'][0]['metrics']['agent_text_chars'],full['rows'][0]['metrics']['agent_text_chars'])
        self.assertEqual(view['projection_metric'],'agent_text_chars')

    def test_unknown_not_zero_and_no_import_order_substitution(self):
        run=self.run_fixture(None);self.store.add([run]);r=report(self.store)
        self.assertEqual(training_series(r,'actions')['cohorts'],[])
        for key in ['recovery_rate','plan_completion_rate','plan_deviation_rate','exploration_rate']:
            self.assertIsNone(r['rows'][0]['metrics'][key]['value'])
        empty=copy.deepcopy(run);empty['events']=[]
        self.assertIsNone(source_record(empty)['metrics']['feedback_link_rate']['value'])

    def test_revisions_replace_current_row_without_erasing_measurements(self):
        p={'producer':'test','rollout_id':'a','revision':0,'state':'in_progress','document':harbor(),'metadata':{'experiment':'trial','training_step':3}}
        first=self.store.ingest(p);self.assertEqual(training_series(report(self.store),'actions')['cohorts'],[])
        p.update(revision=1,state='complete');p['document']=copy.deepcopy(p['document']);p['document']['steps'][-1]['message']='Updated'
        last=self.store.ingest(p);r=report(self.store)
        self.assertEqual([v['run_id'] for v in r['rows']],[last['id']])
        with self.store.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM rollout_measurements').fetchone()[0],2)
        self.assertNotEqual(first['id'],last['id'])

    def test_cohort_and_task_mix_are_preserved_and_rollouts_not_pooled(self):
        self.store.add([self.run_fixture(0,task_id='A',split='train'),self.run_fixture(0,task_id='B',split='train'),self.run_fixture(0,task_id='C',split='eval')])
        series=training_series(report(self.store),'feedback_link_rate')
        self.assertEqual(len(series['cohorts']),2)
        train=next(v for v in series['cohorts'] if v['cohort']['split']=='train')
        self.assertEqual(train['bins'][0]['n'],2)
        self.assertEqual(train['bins'][0]['tasks'],{'A':1,'B':1})
        self.assertEqual(len(train['points']),2)

    def test_explicit_false_success_and_other_participants_do_not_disappear(self):
        run=self.run_fixture();run['outcome']['verified_success']=False
        original=source_record(run);action=next(e for e in run['events'] if e['kind']=='action')
        other=copy.deepcopy(action);other.update(id='other',index=1000,actor='user');run['events'].append(other)
        self.assertEqual(source_record(run)['metrics']['actions']['value'],original['metrics']['actions']['value'])
        self.assertEqual(original['metrics']['recorded_success']['value'],0)
        expected=sum(len(e['text']) for e in run['events'] if e['actor']=='agent' and not e.get('copied_context') and e['kind'] in {'reasoning','message'})
        self.assertGreater(expected,0)
        self.assertEqual(original['metrics']['agent_text_chars']['value'],expected)

    def test_plan_attempt_denominator_is_unique_stages_not_relation_count(self):
        run=self.run_fixture();self.store.add([run]);e=next(e for e in run['events'] if e['kind']=='action')
        plan={'id':'p','actor':'agent','kind':'semantic','activity':'plan','source':{'event_id':e['id']},'plan_structure':{'steps':[{'id':'a'},{'id':'b'}]}}
        action={'id':'a','actor':'agent','kind':'action','source':{'event_id':e['id']}}
        relation={'from':'a','to':'p','type':'attempts_plan_step','plan_step_id':'a'}
        doc={'source_hash':digest(run),'units':[plan,action],'relations':[relation,relation]}
        bundle={'document':doc,'observer':{'id':'test','label':'test'}}
        record=semantic_record(run,bundle);self.assertEqual(record['metrics']['plan_stage_attempt_fraction']['value'],.5)
        self.assertIsNone(record['metrics']['plan_completion_rate']['value'])
        record_map(self.store,run,bundle);bundle['document']['sequence_patterns']={'schema':'new-projection'};record_map(self.store,run,bundle)
        bundle['document']['plan_execution']={'schema':'new-projection'};record_map(self.store,run,bundle)
        self.assertEqual(len([r for r in report(self.store)['rows'] if r['observer']=='test']),1)

    def test_activity_scope_includes_tool_checks_without_rewriting_prose_metrics(self):
        run=self.run_fixture();event=next(e for e in run['events'] if e['kind']=='action')
        def unit(identifier,kind,activity,actor='agent'):
            return dict(id=identifier,kind=kind,activity=activity,actor=actor,source={'event_id':event['id']})
        doc={'source_hash':digest(run),'units':[
            unit('check','action','verify'),unit('next','semantic','orient'),
            unit('unknown','semantic','unresolved'),unit('legacy','action',None),
            unit('feedback','feedback','verify','environment'),unit('user','semantic','plan','user')],
            'relations':[]}
        bundle={'document':doc,'observer':{'id':'scoped','label':'scoped'}}
        record=semantic_record(run,bundle);metrics=record['metrics']
        self.assertEqual(metrics['activity_verify_share']['value'],0)
        self.assertEqual(metrics['activity_verify_share']['denominator'],2)
        self.assertEqual(metrics['agent_verify_unit_share']['value'],1/3)
        self.assertEqual(metrics['agent_verify_unit_share']['evidence_ids'],['check'])
        self.assertEqual(record['activity_counts'],{'orient':1,'unresolved':1})
        self.assertEqual(record['agent_activity_counts'],{'verify':1,'orient':1,'unresolved':1})
        doc['units']=[]
        self.assertIsNone(semantic_record(run,bundle)['metrics']['agent_verify_unit_share']['value'])
        self.assertIsNone(source_record(run)['metrics']['agent_verify_unit_share']['value'])

    def test_v18_activity_extension_uses_linked_graph_and_preserves_historical_prose_values(self):
        from tracker.rollout_metrics import save,ensure_current
        from tracker.graph_store import build,save as save_graph
        run=self.run_fixture();self.store.add([run]);event=next(e for e in run['events'] if e['kind']=='action')
        doc={'source_hash':digest(run),'units':[{'id':'check','kind':'action','actor':'agent',
            'activity':'verify','source':{'event_id':event['id']}}],'relations':[]}
        bundle={'document':doc,'observer':{'id':'v18-control','label':'v18 control'}}
        graph=build(run,bundle);old=semantic_record(run,bundle);old['schema']='rollout-behavior/18'
        old['graph_id']=graph['id'];old.pop('agent_activity_counts');old.pop('agent_activity_scope')
        for key in ('agent_verify_unit_share','agent_plan_unit_share'):old['metrics'].pop(key)
        with self.store.connect() as c:save_graph(c,graph);save(c,old)
        current=next(row for row in report(self.store)['rows'] if row['observer']=='v18-control')
        self.assertEqual(current['metrics']['agent_verify_unit_share']['value'],1)
        self.assertEqual(current['metrics']['activity_verify_share'],old['metrics']['activity_verify_share'])
        self.assertEqual(current['annotation_hash'],old['annotation_hash'])
        self.assertEqual(current['graph_id'],graph['id'])
        self.assertEqual(ensure_current(self.store),0)

    def test_execution_report_denominators_keep_uninspected_negatives_unknown(self):
        from tracker.execution_reports import bound_responses, VERSION
        run=self.run_fixture();pairs=bound_responses(run);self.assertEqual(len(pairs),3)
        rows=[{'action_event_id':a['id'],'response_event_id':f['id'],'error':'reported' if i==0 else 'not_reported',
               'warning':'not_reported','complete_readable_response':i==2} for i,(a,f) in enumerate(pairs)]
        doc={'source_hash':digest(run),'units':[],'relations':[],
             'execution_reports':{'schema':VERSION,'source_hash':digest(run),'observations':rows},
             'execution_returns':[]}
        bundle={'document':doc,'observer':{'id':'reports','label':'reports'}}
        m=semantic_record(run,bundle)['metrics']
        self.assertEqual(m['execution_error_report_fraction']['numerator'],1)
        self.assertEqual(m['execution_error_report_fraction']['denominator'],2)
        self.assertEqual(m['execution_error_unknown_fraction']['value'],1/3)
        self.assertEqual(m['execution_report_coverage']['value'],1)
        self.assertEqual(m['execution_warning_report_fraction']['denominator'],1)
        self.assertIsNone(m['recovery_rate']['value'])
        rows[1]['action_event_id']=rows[0]['action_event_id']
        with self.assertRaisesRegex(InputError,'unbound'):semantic_record(run,bundle)
