import copy
import json
import tempfile
import unittest
from pathlib import Path

from tracker import strategy_profiles as s, graph_store as gs, monitoring
from tracker.adapters import normalize
from tracker.rollout_metrics import source_record, save
from tracker.schema import digest, dumps, InputError
from tracker.store import Store
from test_tracker import harbor


def retry(changed=True, outcome='completed', anchor='a'):
    return {'failed_event_id': anchor, 'failed_unit_id': 'unit-'+anchor,
            'retry_event_id': anchor+'-retry', 'retry_unit_id': 'unit-'+anchor+'-retry',
            'payload_changed': changed, 'retry_outcome': outcome,
            'evidence_ids': [anchor, anchor+'-result', anchor+'-retry', anchor+'-retry-result']}


def feedback(value, closed=True, complete=True, anchor='a'):
    return {'action_event_id': anchor, 'response_event_ids': [anchor+'-result'],
            'expression_event_ids': [anchor+'-text'], 'assessment_event_id': anchor+'-text' if value == 1 else None,
            'boundary_event_id': anchor+'-next' if closed else None,
            'closed_window': closed, 'complete_readable_evidence': complete, 'value': value, 'reason': None}


class StrategyDerivationTests(unittest.TestCase):
    def record(self, **kw):
        return {'run_id': 'r', 'observer': 'o', 'source_hash': 'hash', **kw}

    def test_failure_partition_keeps_unknown_payload_and_missing_return(self):
        record=self.record(retry_observation={'episodes':[retry(), retry(False,'partial','b'), retry(None,'completed','c')],
                                             'failed_calls_without_selected_retry':['d']})
        es=s.derive(record)['families']['failure']; c=s.counts(es,'failure')
        self.assertEqual(c['categories'],{'changed':1,'unchanged':1,'unknown':2})
        self.assertEqual((c['numerator'],c['denominator'],c['value']),(1,2,.5))
        self.assertEqual((c['completed'],c['terminal']),(2,3))
        self.assertIn('does not establish stopping',es[-1]['reason'])

    def test_outcome_unknown_is_not_failure(self):
        es=s.derive(self.record(retry_observation={'episodes':[retry(outcome='not_established')],
                                                'failed_calls_without_selected_retry':[]}))['families']['failure']
        c=s.counts(es,'failure');self.assertEqual((c['known'],c['terminal'],c['outcome_unknown']),(1,0,1))

    def test_linked_adjustment_outcome_trend_does_not_require_native_payload(self):
        es=[{'category':'unknown','selected_retry':True,'adjustment_observed':True,'outcome':v} for v in ('completed','failed','not_established')]
        es.append({'category':'changed','selected_retry':True,'adjustment_observed':False,'outcome':'completed'})
        c=s.counts(es,'failure','adjustment_completion')
        self.assertEqual((c['numerator'],c['denominator'],c['value']),(1,2,.5))
        self.assertEqual(c['outcome_unknown'],1)

    def test_duplicate_anchors_rejected_instead_of_double_counted(self):
        for es,missing in [([retry(),retry()],[]),([retry()],['a'])]:
            with self.assertRaises(InputError):s.derive(self.record(retry_observation={'episodes':es,'failed_calls_without_selected_retry':missing}))

    def test_adjustment_path_keeps_natural_language_and_identity(self):
        r=self.record(retry_observation={'episodes':[retry()],'failed_calls_without_selected_retry':[]},
                      linked_adjustment_observation={'episodes':[{'failed_event_id':'a','retry_event_id':'a-retry','changes':[
                          {'declaration_unit_id':'decl','execution_unit_id':'act','work':'Add the missing decorator to the reproduction.'}]}]})
        before=copy.deepcopy(r);e=s.derive(r)['families']['failure'][0]
        self.assertEqual(e['adjustments'][0]['work'],'Add the missing decorator to the reproduction.')
        self.assertEqual(e['stages'][2]['refs'],['act']);self.assertTrue(e['adjustment_observed']);self.assertEqual(r,before)

    def test_multiple_adjustment_paths_group_unique_witnesses_without_inventing_sequence(self):
        a={'declaration_unit_id':'decl','execution_unit_id':'act','work':'Fix a dependency'}
        r=self.record(retry_observation={'episodes':[retry()],'failed_calls_without_selected_retry':[]},
                      linked_adjustment_observation={'episodes':[{'failed_event_id':'a','retry_event_id':'a-retry','changes':[a,{**a,'execution_unit_id':'act2'}]}]})
        e=s.derive(r)['families']['failure'][0]
        self.assertEqual(e['stages'][1]['refs'],['decl']);self.assertEqual(e['stages'][2]['refs'],['act','act2'])
        self.assertEqual(len(e['adjustments']),2)

    def test_feedback_requires_closed_complete_window_but_keeps_positive_open_evidence(self):
        observations=[feedback(1),feedback(0,anchor='b'),feedback(1,False,anchor='c'),feedback(0,complete=False,anchor='d'),feedback(None,anchor='e')]
        es=s.derive(self.record(feedback_assessment={'schema':'feedback-assessment/2','observations':observations}))['families']['feedback']
        c=s.counts(es,'feedback');self.assertEqual(c['categories'],{'assessed':1,'unassessed':1,'unknown':3})
        self.assertEqual(c['value'],.5);self.assertEqual(es[2]['stages'][1]['event_id'],'c-text')

    def test_rejected_legacy_feedback_does_not_reappear(self):
        self.assertEqual(s.derive(self.record(feedback_assessment={'schema':'feedback-assessment/1','observations':[feedback(1)]}))['families'],{})


class StrategyStoreTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.store=Store(Path(temp.name)/'test.sqlite')

    def run_fixture(self, nonce=0, **metadata):
        raw=harbor();raw['steps'][-1]['message']+=' '+str(nonce)
        run=normalize(raw,'harbor',{'experiment':'test','task_id':'same-task','training_step':2,**metadata})[0]
        self.store.add([run]);return run

    def observation(self, run, observer='review', episodes=None, **changes):
        record=source_record(run);record.update(observer=observer,observer_label='Review '+observer)
        record['retry_observation']={'episodes':episodes if episodes is not None else [retry()], 'failed_calls_without_selected_retry':[]}
        graph=gs.build(run,{'document':{'source_hash':digest(run),'units':[], 'relations':[]},'observer':{'id':observer,'label':'Review'}})
        record['graph_id']=graph['id'];record.update(changes)
        with self.store.connect() as c:gs.save(c,graph);identifier=save(c,record)
        return identifier,record,graph

    def test_sync_idempotent_and_exact_graph_read_survives_later_graph(self):
        run=self.run_fixture();identifier,record,graph=self.observation(run)
        self.assertEqual(s.sync(self.store),1);self.assertEqual(s.sync(self.store),0)
        p=s.snapshot(self.store);self.assertEqual(p['counts']['total'],1)
        newer=copy.deepcopy(graph);newer['observer_label']='Later projection'
        newer['id']='graph-'+digest({k:v for k,v in newer.items() if k!='id'})
        with self.store.connect() as c:gs.save(c,newer)
        evidence=s.read(self.store,p['cases'][0]['profile_id'])
        self.assertEqual(evidence['graph']['id'],graph['id']);self.assertEqual(evidence['input_observation'],record)
        self.assertIn('episode=',p['cases'][0]['map_url']);self.assertEqual(evidence['input_id'],identifier)

    def test_live_sync_materializes_profiles_without_monitor_definition(self):
        self.observation(self.run_fixture());monitoring.sync(self.store)
        self.assertEqual(s.snapshot(self.store)['counts']['total'],1)

    def test_source_only_version_upgrade_reuses_values_without_reanalyzing_trace(self):
        from unittest.mock import patch
        from tracker.rollout_metrics import ensure_current, VERSION
        run=self.run_fixture();old=source_record(run);old['schema']='rollout-behavior/13'
        with self.store.connect() as c:
            c.execute('DELETE FROM rollout_measurements WHERE run_id=?',(run['id'],));save(c,old)
        with patch('tracker.rollout_metrics.source_record',side_effect=AssertionError('Unnecessary source analysis')):
            ensure_current(self.store)
        with self.store.connect() as c:
            current=json.loads(c.execute("SELECT document FROM rollout_measurements WHERE json_extract(document,'$.schema')=?",(VERSION,)).fetchone()[0])
        self.assertEqual(current,{**old,'schema':VERSION})

    def test_migration_repairs_placeholder_metric_and_keeps_original_graph_and_history(self):
        from tracker.rollout_metrics import ensure_current, VERSION
        raw={'trajectory_format':'devai/1','trajectory':[
            {'step':0,'agent':{'action':'Running command: install package'},'environment':'Permission denied'},
            {'step':1,'agent':{'action':'Running command: install --user package'},'environment':'Installed'}]}
        run=normalize(raw)[0];self.store.add([run])
        actions=[e for e in run['events'] if e['kind']=='action'];e=retry(False)
        e.update(failed_event_id=actions[0]['id'],retry_event_id=actions[1]['id'])
        identifier,record,graph=self.observation(run,episodes=[e],schema='rollout-behavior/13')
        ensure_current(self.store);s.sync(self.store);p=s.snapshot(self.store)
        self.assertEqual(p['counts']['categories']['unknown'],1)
        self.assertEqual((p['counts']['completed'],p['counts']['terminal']),(1,1))
        d=s.read(self.store,p['cases'][0]['profile_id']);self.assertEqual(d['graph']['id'],graph['id'])
        self.assertEqual(d['input_observation']['schema'],VERSION)
        self.assertIsNone(d['input_observation']['metrics']['unchanged_retry_fraction']['value'])
        with self.store.connect() as c:
            old=json.loads(c.execute('SELECT document FROM rollout_measurements WHERE id=?',(identifier,)).fetchone()[0])
        self.assertEqual(old,record);self.assertEqual(ensure_current(self.store),0)

    def test_newer_input_without_family_does_not_fallback_to_stale_profile(self):
        run=self.run_fixture();self.observation(run);s.sync(self.store)
        self.observation(run,retry_observation=None);s.sync(self.store)
        self.assertEqual(s.snapshot(self.store)['measured_rollouts'],0)

    def test_observers_and_task_configuration_are_not_pooled(self):
        for i,meta in enumerate([{}, {'task_id':'other'}, {'sampling':{'temperature':.2}}]):
            self.observation(self.run_fixture(i,**meta),observer='review')
        self.observation(self.run_fixture(9),observer='other')
        s.sync(self.store);p=s.snapshot(self.store,observer='review')
        self.assertEqual(len(p['observers']),2);self.assertEqual(len(p['cohorts']),3)
        self.assertEqual(p['measured_rollouts'],1);self.assertEqual(p['counts']['total'],1)

    def test_unknown_tasks_cannot_form_a_matched_cohort(self):
        self.assertNotEqual(s.cohort({},'a'),s.cohort({},'b'))

    def test_latest_observer_default_does_not_prefer_larger_legacy_sample(self):
        run=self.run_fixture();self.observation(run,'old',[retry(anchor=str(i)) for i in range(5)])
        self.observation(run,'new');s.sync(self.store)
        self.assertEqual(s.snapshot(self.store)['observer'],'new')

    def test_training_pools_opportunities_and_counts_unannotated_population(self):
        self.observation(self.run_fixture(0),episodes=[retry()])
        self.observation(self.run_fixture(1),episodes=[retry(False,anchor=str(i)) for i in range(9)])
        self.run_fixture(2)
        s.sync(self.store);p=s.snapshot(self.store)
        self.assertEqual((p['population'],p['measured_rollouts']),(3,2))
        self.assertEqual((p['bins'][0]['value'],p['bins'][0]['denominator']),(.1,10))
        self.assertEqual(len(p['points']),3)
        self.assertEqual(p['bins'][0]['coverage'],2/3)
        self.assertEqual(sum(r['status']=='awaiting_observation' for r in p['points']),1)

    def test_missing_coordinates_stay_unplaced(self):
        self.observation(self.run_fixture(training_step=None));s.sync(self.store);p=s.snapshot(self.store)
        self.assertEqual(p['bins'],[]);self.assertIsNone(p['points'][0]['step']);self.assertEqual(p['missing_training_coordinates'],1)

    def test_source_mismatch_excluded_and_export_rejects_tampering(self):
        run=self.run_fixture();self.observation(run,source_hash='bad');s.sync(self.store)
        self.assertEqual(s.snapshot(self.store)['measured_rollouts'],0)
        with self.store.connect() as c:identifier=c.execute('SELECT id FROM strategy_profile_observations').fetchone()[0]
        with self.assertRaisesRegex(InputError,'identity mismatch'):s.read(self.store,identifier)

    def test_derived_document_tampering_rejected(self):
        self.observation(self.run_fixture());s.sync(self.store)
        identifier=s.snapshot(self.store)['cases'][0]['profile_id']
        with self.store.connect() as c:
            d=json.loads(c.execute('SELECT document FROM strategy_profile_observations WHERE id=?',(identifier,)).fetchone()[0])
            d['families']['failure'][0]['category']='unchanged'
            c.execute('UPDATE strategy_profile_observations SET document=? WHERE id=?',(dumps(d),identifier))
        with self.assertRaisesRegex(InputError,'differs'):s.read(self.store,identifier)

    def test_incomplete_rollout_excluded(self):
        result=self.store.ingest({'producer':'test','rollout_id':'r','revision':0,'state':'in_progress','document':harbor(),'metadata':{'task_id':'same-task'}})
        with self.store.connect() as c:run=json.loads(c.execute('SELECT document FROM runs WHERE id=?',(result['id'],)).fetchone()[0])
        self.observation(run);s.sync(self.store);self.assertEqual(s.snapshot(self.store)['counts']['total'],0)

    def test_changed_map_excludes_old_profile_and_reports_coverage_gap(self):
        from tracker import behavior_distributions
        run=self.run_fixture();self.observation(run);s.sync(self.store)
        before=s.snapshot(self.store,observer='review')
        graph=gs.build(run,{'document':{'source_hash':digest(run),'units':[],
            'relations':[],'annotation':'changed'},'observer':{'id':'review','label':'Review'}})
        with self.store.connect() as c:gs.save(c,graph)
        current=s.snapshot(self.store,observer='review')
        self.assertEqual(current['counts']['total'],0)
        self.assertEqual(current['population'],1)
        self.assertEqual(current['coverage']['stale_observation'],1)
        self.assertEqual(current['points'][0]['status'],'stale_observation')
        self.assertIsNone(current['bins'][0]['value'])
        self.assertEqual(behavior_distributions.inputs(self.store,'failure'),[])
        self.assertEqual(len(s.read(self.store,before['cases'][0]['profile_id'])['families']['failure']),1)

    def test_training_comparison_keeps_policy_versions_and_missing_step_observations(self):
        self.observation(self.run_fixture(0,training_step=0,policy_version='p0',checkpoint='c0'))
        self.run_fixture(1,training_step=1,policy_version='p1',checkpoint='c1')
        self.observation(self.run_fixture(2,training_step=2,policy_version='p2',checkpoint='c2'),episodes=[retry(False)])
        s.sync(self.store)
        fixed=s.snapshot(self.store,observer='review',comparison='fixed_policy')
        self.assertEqual(len(fixed['cohorts']),3)
        result=s.snapshot(self.store,observer='review',comparison='training')
        self.assertEqual((len(result['cohorts']),result['population'],result['measured_rollouts']),(1,3,2))
        self.assertEqual([p['policy_version'] for p in result['points']],['p0','p1','p2'])
        self.assertEqual([b['value'] for b in result['bins']],[1,None,0])
        self.assertEqual([b['coverage'] for b in result['bins']],[1,0,1])
        self.assertEqual(result['coverage']['awaiting_observation'],1)

    def test_training_comparison_keeps_task_and_sampling_controls_and_unplaced_policy(self):
        for i,metadata in enumerate([{'policy_version':'p0'}, {'policy_version':'p1'},
                {'policy_version':'p2','sampling':{'temperature':.2}},
                {'policy_version':'p3','task_id':'another'}, {'policy_version':'p4','training_step':None}]):
            self.observation(self.run_fixture(i,**metadata))
        s.sync(self.store)
        result=s.snapshot(self.store,comparison='training',observer='review')
        self.assertEqual(len(result['cohorts']),4)
        self.assertEqual(result['measured_rollouts'],2)
        self.assertEqual(len(result['bins'][0]['policies']),2)

    def test_late_old_publication_and_concurrent_read_keep_matching_profile(self):
        from unittest.mock import patch
        from tracker import measurement_lineage
        run=self.run_fixture();_,old,old_graph=self.observation(run)
        new_graph=gs.build(run,{'document':{'source_hash':digest(run),'units':[],
            'relations':[],'annotation':'changed'},'observer':{'id':'review','label':'Review'}})
        new=copy.deepcopy(old);new['graph_id']=new_graph['id'];new['retry_observation']['episodes']=[retry(False)]
        late=copy.deepcopy(old);late['scope']='older worker finished later'
        with self.store.connect() as c:gs.save(c,new_graph);save(c,new);save(c,late)
        s.sync(self.store)
        self.assertEqual(s.snapshot(self.store,observer='review')['counts']['value'],0)
        original=measurement_lineage.resolve
        def arrive(*args,**kwargs):
            result=original(*args,**kwargs)
            third=copy.deepcopy(new_graph);third['annotation_hash']='different';third.pop('id');third['id']='graph-'+digest(third)
            with self.store.connect() as c:gs.save(c,third)
            return result
        with patch.object(measurement_lineage,'resolve',side_effect=arrive):
            self.assertEqual(s.snapshot(self.store,observer='review')['counts']['value'],0)
        self.assertEqual(s.snapshot(self.store,observer='review')['measured_rollouts'],0)

    def test_policy_zero_and_missing_identity_stay_distinct_and_clocks_do_not_pool(self):
        self.observation(self.run_fixture(0,policy_version=0,training_clock='generation'))
        self.observation(self.run_fixture(1,training_clock='generation'))
        self.observation(self.run_fixture(2,policy_version=0,training_clock='learner'))
        s.sync(self.store)
        result=s.snapshot(self.store,comparison='training',observer='review')
        self.assertEqual(len(result['cohorts']),2)
        self.assertEqual(result['bins'][0]['policies'],[{'policy_version':0,'checkpoint':None}])
        self.assertEqual(result['bins'][0]['policy_missing_rollouts'],1)

    def test_empty_observer_and_invalid_family_do_not_substitute(self):
        self.observation(self.run_fixture());s.sync(self.store)
        self.assertEqual(s.snapshot(self.store,observer='missing')['counts']['total'],0)
        with self.assertRaises(InputError):s.snapshot(self.store,family='personality')
