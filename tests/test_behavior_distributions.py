import copy
import json
import tempfile
import unittest
from pathlib import Path

from tracker import behavior_distributions as d, graph_store as gs, strategy_profiles as profiles
from tracker.adapters import normalize
from tracker.schema import InputError, digest
from tracker.store import Store
from tracker.rollout_metrics import source_record, save
from test_tracker import harbor
from test_strategy_profiles import retry, feedback


class DistributionTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.store=Store(Path(temp.name)/'test.sqlite')

    def run_fixture(self,nonce=0,**metadata):
        raw=harbor();raw['steps'][-1]['message']+=' '+str(nonce)
        run=normalize(raw,'harbor',{'experiment':'test','task_id':'same-task','training_step':2,**metadata})[0]
        self.store.add([run]);return run

    def graph(self,run,activities=('orient','verify'),observer='review',extra=()):
        event=next(e for e in run['events'] if e['actor']=='agent')
        units=[{'id':'unit-'+str(i),'actor':'agent','kind':'semantic','activity':a,
                'source':{'event_id':event['id'],'start':0,'end':len(event['text']),'text':event['text'],'source_pointer':'/steps/1/message'}} for i,a in enumerate(activities)]
        graph=gs.build(run,{'document':{'source_hash':digest(run),'units':units+list(extra),'relations':[]},'observer':{'id':observer,'label':'Reviewed units'}})
        with self.store.connect() as c:gs.save(c,graph)
        return graph

    def test_grouping_versions_are_exclusive_and_immutable(self):
        value={'name':'Work','groups':[{'id':'work','label':'Work','activities':['orient','verify']}]}
        a=d.save_grouping(self.store,value);self.assertEqual(a,d.save_grouping(self.store,value))
        value['groups'][0]['activities']=['orient'];b=d.save_grouping(self.store,value)
        self.assertNotEqual(a['id'],b['id']);self.assertEqual(len(d.groupings(self.store)),3)
        for changes in [[{'id':'unknown','label':'X','activities':['orient']}],
                        [{'id':'a','label':'A','activities':['orient']},{'id':'b','label':'B','activities':['orient']}],
                        [{'id':'a','label':'A','activities':['fake']}],
                        [{'id':'a','label':'A','activities':['orient','orient']}]]:
            with self.assertRaises(InputError):d.save_grouping(self.store,{'name':'bad','groups':changes})

    def test_builtin_grouping_covers_the_full_base_standard_once(self):
        from tracker.base_units import ACTIVITIES
        from tracker.base_standard import definitions
        labels=set(definitions(ACTIVITIES))-{'other','unresolved'}
        assigned=[a for g in d.DEFAULT_GROUPS for a in g['activities']]
        self.assertTrue(labels.issubset(assigned));self.assertEqual(len(assigned),len(set(assigned)))

    def test_equal_rollouts_and_pooling_answer_different_questions(self):
        points=[{'counts':{'a':1,'unknown':0},'total':1},{'counts':{'a':0,'unknown':9},'total':9}]
        self.assertEqual(d.aggregate(points,['a','unknown'],'rollout')['shares'],{'a':.5,'unknown':.5})
        self.assertEqual(d.aggregate(points,['a','unknown'],'opportunity')['shares'],{'a':.1,'unknown':.9})
        self.assertEqual(d.aggregate([],['a'],'rollout')['shares'],{'a':None})

    def test_only_agent_units_count_and_unmapped_is_preserved(self):
        run=self.run_fixture();g=self.graph(run,('orient','verify',None),extra=[
            {'id':'feedback','actor':'agent','kind':'feedback','activity':'verify'},
            {'id':'user','actor':'user','kind':'semantic','activity':'orient'}])
        self.assertEqual(d.sync(self.store),1);self.assertEqual(d.sync(self.store),0)
        grouping=d.save_grouping(self.store,{'name':'Frame','groups':[{'id':'frame','label':'Frame','activities':['orient']}]})
        s=d.snapshot(self.store,grouping=grouping['id'])
        self.assertEqual(s['distribution']['counts'],{'frame':1,'unknown':2});self.assertEqual(s['distribution']['total'],3)
        self.assertEqual({x['graph_id'] for x in s['cases']},{g['id']})
        self.assertTrue(all('graph='+g['id'] in x['map_url'] and 'focus_unit=' in x['map_url'] for x in s['cases']))
        self.assertEqual([n['activity'] for n in gs.read(self.store,g['id'])['nodes'] if n['id']=='unit-1'],['verify'])

    def test_empty_new_graph_does_not_fallback_or_double_count(self):
        run=self.run_fixture();self.graph(run);d.sync(self.store)
        self.graph(run,());d.sync(self.store)
        self.assertEqual(d.snapshot(self.store)['observed_rollouts'],0)
        with self.store.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM behavior_unit_inputs').fetchone()[0],2)

    def test_missing_annotations_are_null_and_windows_are_inclusive(self):
        self.graph(self.run_fixture(1,training_step=1),('orient',))
        self.run_fixture(2,training_step=2)
        self.graph(self.run_fixture(3,training_step=3),('verify',))
        d.sync(self.store);s=d.snapshot(self.store)
        self.assertEqual((s['population'],s['observed_rollouts']),(3,2));self.assertEqual([b['step'] for b in s['bins']],[1,2,3])
        self.assertIsNone(s['bins'][1]['shares']['frame']);self.assertEqual(s['bins'][1]['population'],1)
        self.assertTrue(s['comparable']);self.assertEqual(next(x for x in s['deltas'] if x['id']=='frame')['pp'],-100)
        ranged=d.snapshot(self.store,a_start=1,a_end=2,b_start=3,b_end=3)
        self.assertEqual((ranged['baseline']['population'],ranged['baseline']['rollouts']),(2,1))
        overlap=d.snapshot(self.store,a_start=1,a_end=3,b_start=3,b_end=3)
        self.assertFalse(overlap['comparable']);self.assertTrue(all(x['pp'] is None for x in overlap['deltas']))

    def test_invalid_bounds_rejected_and_empty_population_can_have_explicit_bounds(self):
        self.assertEqual(d.snapshot(self.store,a_start=10)['baseline']['total'],0)
        for kw in [{'a_start':-1},{'a_start':True},{'a_start':4,'a_end':2},{'a_start':'a'}]:
            with self.assertRaises(InputError):d.snapshot(self.store,**kw)

    def test_task_configuration_and_protocols_never_pool(self):
        self.graph(self.run_fixture(1));self.graph(self.run_fixture(2,task_id='other'));self.graph(self.run_fixture(3,sampling={'temperature':1}))
        self.graph(self.run_fixture(4),observer='other');d.sync(self.store);s=d.snapshot(self.store,observer='review')
        self.assertEqual(len(s['observers']),2);self.assertEqual(len(s['cohorts']),3);self.assertEqual(s['observed_rollouts'],1)
        self.assertEqual(d.snapshot(self.store,experiment='missing')['observed_rollouts'],0)

    def test_unplaced_data_does_not_acquire_fake_training_positions(self):
        self.graph(self.run_fixture(training_step=None));d.sync(self.store);s=d.snapshot(self.store)
        self.assertEqual((s['observed_rollouts'],s['unplaced_rollouts']),(1,1));self.assertEqual(s['bins'],[])
        self.assertFalse(s['comparable']);self.assertEqual(s['distribution']['total'],2)

    def test_logged_policy_changes_do_not_partition_a_training_curve(self):
        self.graph(self.run_fixture(1,training_step=1,policy_version='v1',checkpoint='c1'))
        self.graph(self.run_fixture(2,training_step=2,policy_version='v2',checkpoint='c2'))
        d.sync(self.store);s=d.snapshot(self.store)
        self.assertEqual(len(s['cohorts']),1);self.assertTrue(s['comparable'])
        self.assertEqual([p['policy_version'] for p in s['points']],['v1','v2'])
        self.assertEqual([p['checkpoint'] for p in s['points']],['c1','c2'])

    def test_unplaced_different_policies_remain_separate(self):
        self.graph(self.run_fixture(1,training_step=None,policy_version='v1'))
        self.graph(self.run_fixture(2,training_step=None,policy_version='v2'))
        d.sync(self.store);s=d.snapshot(self.store)
        self.assertEqual(len(s['cohorts']),2);self.assertEqual(s['observed_rollouts'],1)

    def test_snapshot_identity_reconciles_to_cases_and_grouping(self):
        self.graph(self.run_fixture());d.sync(self.store);s=d.snapshot(self.store)
        self.assertEqual(s,d.snapshot(self.store));self.assertEqual(s['snapshot_id'],'distribution-'+digest({k:v for k,v in s.items() if k!='snapshot_id'}))
        for c in s['categories']:self.assertEqual(s['distribution']['counts'][c['id']],len([r for r in s['cases'] if r['category']==c['id']]))

    def test_response_lenses_keep_missing_links_and_outcomes_distinct(self):
        run=self.run_fixture();g=self.graph(run);record=source_record(run)
        record.update(observer='review',observer_label='Review',graph_id=g['id'],
                      retry_observation={'episodes':[retry(None,'not_established')],'failed_calls_without_selected_retry':['b']},
                      feedback_assessment={'schema':'feedback-assessment/2','observations':[feedback(1),feedback(0,anchor='b'),feedback(None,anchor='c')]})
        with self.store.connect() as c:save(c,record)
        profiles.sync(self.store)
        failure=d.snapshot(self.store,lens='failure');self.assertEqual(failure['distribution']['counts'],{'adjustment':0,'retry':1,'unknown':1})
        outcome=d.snapshot(self.store,lens='outcome');self.assertEqual(outcome['distribution']['counts'],{'completed':0,'failed':0,'partial':0,'unknown':1})
        f=d.snapshot(self.store,lens='feedback');self.assertEqual(f['distribution']['counts'],{'assessed':1,'unassessed':1,'unknown':1})
        self.assertTrue(all('profile=' in x['map_url'] for x in f['cases']))

    def test_entirely_unobserved_cohorts_remain_selectable_without_zero_behavior(self):
        self.run_fixture(1,task_id='unreviewed-a');self.run_fixture(2,task_id='unreviewed-b')
        s=d.snapshot(self.store,observer='review')
        self.assertEqual(len(s['cohorts']),2)
        self.assertEqual((s['population'],s['observed_rollouts']),(1,0))
        self.assertEqual(s['observation_readiness']['statuses']['not_observed'],1)
        self.assertTrue(all(v is None for v in s['distribution']['shares'].values()))
        other=next(c for c in s['cohorts'] if c['id']!=s['cohort_id'])
        selected=d.snapshot(self.store,observer='review',cohort_id=other['id'])
        self.assertEqual(selected['population'],1)
        self.assertEqual(selected['metadata'],other['metadata'])

    def test_equal_coverage_can_hide_different_annotation_selection_and_catchup_changes_only_observed_mix(self):
        pending=[]
        for step in [0,1]:
            for i,task in enumerate(['A','A','B','B']):
                run=self.run_fixture(step*4+i,training_step=step,task_id=task)
                activity='verify' if task=='A' else 'construct'
                if (step==0 and task=='A') or (step==1 and task=='B'):self.graph(run,(activity,))
                else:pending.append((run,activity))
        d.sync(self.store);first=d.snapshot(self.store,observer='review',population_mode='task_mix')
        self.assertEqual([x['observation_readiness']['coverage'] for x in first['bins']],[.5,.5])
        self.assertEqual(next(x for x in first['deltas'] if x['id']=='check')['pp'],-100)
        for window in ['baseline','current']:
            selection=first[window]['observation_readiness']['selection'][0]
            self.assertEqual(selection['field'],'task_id');self.assertEqual(selection['measured_mix_distance'],.5)
        before=copy.deepcopy(first)
        for run,activity in pending:self.graph(run,(activity,))
        d.sync(self.store);last=d.snapshot(self.store,observer='review',population_mode='task_mix')
        self.assertEqual([x['observation_readiness']['coverage'] for x in last['bins']],[1,1])
        self.assertEqual(next(x for x in last['deltas'] if x['id']=='check')['pp'],0)
        self.assertEqual(last['population'],first['population']);self.assertEqual(first,before)
        self.assertNotEqual(first['snapshot_id'],last['snapshot_id'])
        self.assertEqual(last['inference_calls'],0)

    def test_unfinished_and_failed_captures_do_not_supply_semantic_rates(self):
        from unittest.mock import patch
        from tracker.monitoring import population
        self.graph(self.run_fixture(1));self.graph(self.run_fixture(2));d.sync(self.store)
        rows=population(self.store);rows[0]['state']='in_progress';rows[1]['state']='failed'
        with patch('tracker.monitoring.population',return_value=rows):s=d.snapshot(self.store,observer='review')
        self.assertEqual(s['population'],2);self.assertEqual(s['observed_rollouts'],0)
        self.assertEqual(s['observation_readiness']['statuses']['source_in_progress'],1)
        self.assertEqual(s['observation_readiness']['statuses']['source_failed'],1)
        self.assertTrue(all(x['observation_saved_at'] is None for x in s['observation_members']))

    def test_latest_unannotated_step_stays_in_default_comparison(self):
        self.graph(self.run_fixture(1,training_step=0))
        self.graph(self.run_fixture(2,training_step=1))
        self.run_fixture(3,training_step=2)
        d.sync(self.store);s=d.snapshot(self.store,observer='review')
        self.assertEqual((s['baseline']['start'],s['current']['end']),(0,2))
        self.assertEqual(s['current']['observation_readiness']['statuses']['not_observed'],1)
        self.assertFalse(s['comparable'])
        self.assertTrue(all(x['after'] is None and x['pp'] is None for x in s['deltas']))
        self.assertIn('later_missing',[c['code'] for c in s['observation_checks']])

    def test_current_annotation_does_not_establish_complete_record_coverage(self):
        run=self.run_fixture(1,training_step=0);self.graph(run)
        d.sync(self.store);s=d.snapshot(self.store,observer='review')
        readiness=s['observation_readiness']
        self.assertEqual(readiness['coverage'],1)
        self.assertEqual(readiness['record_coverage']['covered'],1)
        self.assertGreater(readiness['record_coverage']['records'],1)
        self.assertIn('earlier_partial_records',[c['code'] for c in s['observation_checks']])


if __name__=='__main__':unittest.main()
